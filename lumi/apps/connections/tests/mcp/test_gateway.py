from __future__ import annotations

import httpx

from apps.connections.mcp.gateway import RemoteResult
from apps.connections.providers.base import TokenSet
from lumi_ai.ports import McpGateway

from .fakes import NOW, build

PROFILE = 1


async def specs(gateway):
    return {s.name: s for s in await gateway.list_tools(PROFILE)}


def test_core_satisfies_the_port():
    gateway, *_ = build()
    assert isinstance(gateway, McpGateway)


async def test_lists_namespaced_tools_with_cost_and_confirmation():
    gateway, *_ = build()
    found = await specs(gateway)
    assert set(found) == {
        "mcp__gdrive__search_files",
        "mcp__gdrive__create_file",
        "mcp__gdrive__files_get_v2",
        "mcp__gdocs__read_document",
        "mcp__gdocs__batch_update",
    }
    assert found["mcp__gdrive__search_files"].cost == "free"
    assert not found["mcp__gdrive__search_files"].requires_confirmation
    assert found["mcp__gdrive__create_file"].cost == "write"
    assert found["mcp__gdrive__create_file"].requires_confirmation
    assert found["mcp__gdocs__batch_update"].requires_confirmation
    # A schema without "type" becomes an object schema the model can use.
    assert found["mcp__gdrive__create_file"].parameters["type"] == "object"


async def test_no_tools_without_a_user_a_grant_or_the_switch():
    gateway, store, transport, _ = build()
    assert await gateway.list_tools(999) == []
    store.tokens.clear()
    assert await gateway.list_tools(PROFILE) == []
    assert transport.opened == []
    off, *_ = build(env={"MCP_ENABLED": "false"})
    assert await off.list_tools(PROFILE) == []


async def test_a_connector_can_be_switched_off_alone():
    gateway, *_ = build(env={"MCP_GDOCS_ENABLED": "false"})
    assert all(name.startswith("mcp__gdrive__") for name in await specs(gateway))


async def test_tools_are_discovered_once_per_ttl():
    gateway, _, transport, clock = build()
    await gateway.list_tools(PROFILE)
    await gateway.list_tools(PROFILE)
    assert len(transport.opened) == 2  # one session per connector
    clock.advance(301)
    await gateway.list_tools(PROFILE)
    assert len(transport.opened) == 4


async def test_a_failing_server_is_skipped_and_not_hammered():
    gateway, _, transport, clock = build()
    transport.fail_with = ConnectionError("down")
    assert await gateway.list_tools(PROFILE) == []
    first = len(transport.opened)
    assert await gateway.list_tools(PROFILE) == []
    assert len(transport.opened) == first  # negative cache
    clock.advance(61)
    transport.fail_with = None
    assert len(await gateway.list_tools(PROFILE)) == 5


async def test_a_hanging_server_cannot_stall_the_turn():
    gateway, _, transport, _ = build(config_env={"MCP_REFRESH_TIMEOUT_SECONDS": "0"})
    transport.hang = True
    assert await gateway.list_tools(PROFILE) == []


async def test_read_tool_runs_with_the_users_bearer_token():
    gateway, _, transport, _ = build()
    result = await gateway.call(PROFILE, "mcp__gdrive__search_files", {"q": "plan"})
    assert result.status == "ok" and result.payload["content"] == "ran search_files"
    assert transport.calls == [("gdrive", "search_files", {"q": "plan"})]
    assert ("gdrive", "AT-FAKE") in transport.opened


async def test_the_server_name_is_used_for_the_real_call():
    gateway, _, transport, _ = build()
    await gateway.call(PROFILE, "mcp__gdrive__files_get_v2", {})
    assert transport.calls[0][1] == "files.get v2"


async def test_unknown_or_unoffered_tools_never_reach_the_server():
    gateway, _, transport, _ = build()
    for name in ("search_files", "mcp__nope__x", "mcp__gdrive__rm_rf", "mcp__gdrive"):
        result = await gateway.call(PROFILE, name, {})
        assert result.status == "error"
    assert transport.calls == []
    assert (await gateway.call(999, "mcp__gdrive__search_files", {})).status == "error"


async def test_a_write_is_parked_and_does_not_run():
    gateway, store, transport, _ = build()
    result = await gateway.call(PROFILE, "mcp__gdrive__create_file", {"title": "Plan"})
    assert result.status == "confirmation_required"
    assert "Plan" in (result.summary or "")
    assert "NOT" in result.payload["message"] or "NOT" in str(result.payload)
    assert transport.calls == []
    assert store.pending[PROFILE].server_tool == "create_file"
    assert store.pending[PROFILE].user_id == 10


async def test_yes_runs_the_parked_write_exactly_once():
    gateway, store, transport, _ = build()
    await gateway.call(PROFILE, "mcp__gdrive__create_file", {"title": "Plan"})
    resolution = await gateway.resolve_pending(PROFILE, "yes, go ahead")
    assert resolution is not None and resolution.tool == "mcp__gdrive__create_file"
    assert resolution.result["status"] == "ok"
    assert "ran create_file" in resolution.note
    assert transport.calls == [("gdrive", "create_file", {"title": "Plan"})]
    assert await gateway.resolve_pending(PROFILE, "yes") is None
    assert len(transport.calls) == 1
    assert PROFILE not in store.pending


async def test_anything_but_a_clear_yes_cancels_the_write():
    gateway, store, transport, _ = build()
    await gateway.call(PROFILE, "mcp__gdrive__create_file", {"title": "Plan"})
    resolution = await gateway.resolve_pending(PROFILE, "change the title first")
    assert resolution is not None and resolution.tool is None
    assert "NOT executed" in resolution.note
    assert transport.calls == [] and PROFILE not in store.pending


async def test_an_expired_write_is_not_run_even_after_a_yes():
    gateway, _, transport, clock = build()
    await gateway.call(PROFILE, "mcp__gdrive__create_file", {"title": "Plan"})
    clock.advance(31 * 60)
    resolution = await gateway.resolve_pending(PROFILE, "yes")
    assert resolution is not None and resolution.tool is None
    assert "expired" in resolution.note and transport.calls == []


async def test_a_new_write_replaces_the_parked_one():
    gateway, _store, transport, _ = build()
    await gateway.call(PROFILE, "mcp__gdrive__create_file", {"title": "A"})
    await gateway.call(PROFILE, "mcp__gdrive__create_file", {"title": "B"})
    await gateway.resolve_pending(PROFILE, "yes")
    assert transport.calls == [("gdrive", "create_file", {"title": "B"})]


async def test_no_pending_write_means_no_resolution():
    gateway, *_ = build()
    assert await gateway.resolve_pending(PROFILE, "yes") is None


async def test_a_failure_after_confirmation_is_reported_not_hidden():
    gateway, _, transport, _ = build()
    await gateway.call(PROFILE, "mcp__gdrive__create_file", {"title": "Plan"})
    transport.results["create_file"] = RemoteResult("quota exceeded", is_error=True)
    resolution = await gateway.resolve_pending(PROFILE, "yes")
    assert resolution is not None
    assert resolution.result["status"] == "error"
    assert "quota exceeded" in resolution.note


async def test_a_disabled_connector_blocks_a_write_that_was_parked_earlier():
    gateway, store, _transport, _ = build()
    await gateway.call(PROFILE, "mcp__gdrive__create_file", {"title": "Plan"})
    off, off_store, off_transport, _ = build(env={"MCP_GDRIVE_ENABLED": "false"})
    off_store.pending = store.pending
    resolution = await off.resolve_pending(PROFILE, "yes")
    assert resolution is not None and resolution.result["status"] == "error"
    assert off_transport.calls == []


async def test_exception_text_never_reaches_the_model():
    gateway, _, transport, _ = build()
    await gateway.list_tools(PROFILE)
    transport.fail_with = RuntimeError("Bearer AT-FAKE leaked")
    result = await gateway.call(PROFILE, "mcp__gdrive__search_files", {})
    assert result.status == "error"
    assert "AT-FAKE" not in (result.error or "") and "RuntimeError" in (
        result.error or ""
    )


async def test_timeout_is_an_error_not_a_hang():
    gateway, _, transport, _ = build(config_env={"MCP_CALL_TIMEOUT_SECONDS": "0"})
    await gateway.list_tools(PROFILE)
    transport.hang = True
    result = await gateway.call(PROFILE, "mcp__gdrive__search_files", {})
    assert result.status == "error"


async def test_an_expiring_token_is_refreshed_and_saved_before_use():
    gateway, store, transport, _ = build()
    store.tokens[10] = TokenSet(
        access_token="AT-OLD",
        refresh_token="RT",
        expires_at=NOW + __import__("datetime").timedelta(seconds=30),
    )
    await gateway.call(PROFILE, "mcp__gdrive__search_files", {})
    assert ("gdrive", "AT-NEW") in transport.opened
    assert (
        store.saved[-1].access_token == "AT-NEW"
        and store.saved[-1].refresh_token == "RT"
    )


async def test_a_dead_grant_asks_the_user_to_reconnect():
    gateway, store, transport, _ = build(
        oauth_handler=lambda r: httpx.Response(400, json={"error": "invalid_grant"})
    )
    store.tokens[10] = TokenSet(
        access_token="AT-OLD",
        refresh_token="RT",
        expires_at=NOW,
    )
    assert await gateway.list_tools(PROFILE) == []
    assert transport.opened == []


async def test_an_allow_list_hides_other_tools_and_blocks_calling_them(monkeypatch):
    import dataclasses

    from apps.connections.mcp import connectors
    from apps.connections.mcp import gateway as gateway_module

    narrowed = tuple(
        dataclasses.replace(c, allowed_tools=("search_files",))
        if c.name == "gdrive"
        else c
        for c in connectors.CONNECTORS
    )
    monkeypatch.setattr(connectors, "CONNECTORS", narrowed)
    monkeypatch.setattr(gateway_module, "CONNECTORS", narrowed)
    core, _, transport, _ = build()
    found = {s.name for s in await core.list_tools(PROFILE)}
    assert "mcp__gdrive__search_files" in found
    assert "mcp__gdrive__create_file" not in found
    result = await core.call(PROFILE, "mcp__gdrive__create_file", {"title": "x"})
    assert transport.calls == [] and result.status != "ok"
