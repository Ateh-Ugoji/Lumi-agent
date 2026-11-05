"""MCP client service (`app/services/mcp.py`) — hermetic, no network.

Covers: spec conversion + allowlist, spec caching and the master switch, read
dispatch, the write-confirmation gate (require -> confirm/cancel/defer), the
registry's `mcp__*` routing, Google token refresh/persistence, and discovery
against a faked MCP session. The only sockets opened here are none: every
network seam (`_open_session`, `_execute_remote`, `_post_token_exchange`) is
monkeypatched.
"""

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.models.mcp_auth_account import MCPAuthAccount
from app.services import mcp, mcp_connectors
from app.tools import registry

GDRIVE_SEARCH = "mcp__gdrive__search_drive_files"
GDOCS_CREATE = "mcp__gdocs__create_document"
DRIVE_READONLY = mcp_connectors.DRIVE_READONLY_SCOPE


class FakeMCPTool:
    def __init__(self, name, description="A tool.", input_schema=None):
        self.name = name
        self.description = description
        self.input_schema = input_schema if input_schema is not None else {"type": "object", "properties": {}}


class FakeSession:
    def __init__(self, tools=(), call_result=None):
        self._tools = list(tools)
        self._call_result = call_result
        self.calls: list[tuple[str, dict | None]] = []

    async def list_tools(self):
        return SimpleNamespace(tools=self._tools)

    async def call_tool(self, name, arguments=None):
        self.calls.append((name, arguments))
        return self._call_result


@pytest.fixture(autouse=True)
def clean_state():
    mcp._reset_state()
    yield
    mcp._reset_state()


@pytest.fixture
async def db(monkeypatch):
    """In-memory schema with app.services.mcp.session_scope patched to it."""
    from contextlib import asynccontextmanager as acm

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import StaticPool
    from sqlmodel import SQLModel
    from sqlmodel.ext.asyncio.session import AsyncSession

    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    @acm
    async def scope():
        async with factory() as session:
            yield session

    monkeypatch.setattr(mcp, "session_scope", scope)
    yield factory
    await engine.dispose()


def _patch_session(monkeypatch, session):
    @asynccontextmanager
    async def fake_open(connector, headers):
        yield session

    monkeypatch.setattr(mcp, "_open_session", fake_open)


def _patch_session_per_connector(monkeypatch, tools_by_connector):
    """fake_open returning DIFFERENT tool lists per connector (both google
    connectors share the one token, so a single fake would arm both)."""

    @asynccontextmanager
    async def fake_open(connector, headers):
        yield FakeSession(tools=tools_by_connector.get(connector.name, []))

    monkeypatch.setattr(mcp, "_open_session", fake_open)


# --- spec conversion + listing ------------------------------------------------


def test_convert_tool_namespaces_and_guards_schema():
    connector = mcp_connectors.get_connector("gdrive")
    spec = mcp._convert_tool(
        connector,
        FakeMCPTool(
            "search_drive_files",
            "Search files.",
            {"properties": {"q": {"type": "string"}}, "required": ["q"]},  # no root "type"
        ),
    )
    assert spec["type"] == "function"
    assert spec["function"]["name"] == GDRIVE_SEARCH
    assert spec["function"]["parameters"]["type"] == "object"  # root type injected
    assert spec["function"]["parameters"]["required"] == ["q"]


def test_convert_tool_allowlist_filters():
    import dataclasses

    connector = mcp_connectors.get_connector("gdrive")
    filtered = dataclasses.replace(connector, allowed_tools=("search_drive_files",))
    keep = mcp._convert_tool(filtered, FakeMCPTool("search_drive_files"))
    drop = mcp._convert_tool(filtered, FakeMCPTool("delete_everything"))
    assert keep is not None
    assert drop is None


def test_list_specs_includes_cache_and_honors_master_switch(monkeypatch):
    mcp._specs["gdrive"] = (
        0.0,
        [{"type": "function", "function": {"name": GDRIVE_SEARCH, "description": "", "parameters": {}}}],
    )
    assert [s["function"]["name"] for s in mcp.list_specs()] == [GDRIVE_SEARCH]

    from app import config

    monkeypatch.setattr(config.get_settings(), "mcp_enabled", False)
    assert mcp.list_specs() == []


# --- read dispatch ------------------------------------------------------------


async def test_read_tool_executes_immediately(monkeypatch):
    seen: dict = {}

    async def fake_remote(connector, full_name, server_tool, arguments):
        seen.update({"connector": connector.name, "server_tool": server_tool, "arguments": arguments})
        return {"tool": GDRIVE_SEARCH, "content": "1 file"}

    monkeypatch.setattr(mcp, "_execute_remote", fake_remote)
    result = await mcp.call_tool(GDRIVE_SEARCH, {"query": "invoice"})

    assert result == {"tool": GDRIVE_SEARCH, "content": "1 file"}
    assert seen["server_tool"] == "search_drive_files"  # sanitized name maps back
    assert seen["arguments"] == {"query": "invoice"}
    assert mcp._pending == {}


# --- write confirmation gate --------------------------------------------------


def test_requires_confirmation_word_classifier():
    assert mcp.requires_confirmation("create_document")
    assert mcp.requires_confirmation("batchUpdateFiles")  # camelCase splits
    assert mcp.requires_confirmation("files_delete")
    assert not mcp.requires_confirmation("search_drive_files")
    assert not mcp.requires_confirmation("get_file_created_time")  # word "created" is not "create"


async def test_write_tool_stops_at_confirmation_then_runs_on_yes(db, monkeypatch):
    registry.set_current_profile_id(7)
    try:
        executed: list[dict] = []

        async def fake_remote(connector, full_name, server_tool, arguments):
            executed.append({"server_tool": server_tool, "arguments": arguments})
            return {"tool": GDOCS_CREATE, "content": "doc abc123 created"}

        monkeypatch.setattr(mcp, "_execute_remote", fake_remote)

        first = await mcp.call_tool(GDOCS_CREATE, {"title": "Launch plan"})
        assert first["status"] == "confirmation_required"
        assert first["tool"] == GDOCS_CREATE
        assert executed == []  # nothing ran yet
        assert 7 in mcp._pending

        resolution = await mcp.resolve_pending(7, "yes, go ahead")
        assert resolution is not None and resolution.tool == GDOCS_CREATE
        assert "doc abc123 created" in resolution.note
        assert executed == [{"server_tool": "create_document", "arguments": {"title": "Launch plan"}}]
        assert mcp._pending == {}
    finally:
        registry.set_current_profile_id(None)


async def test_write_tool_cancelled_without_confirmation(db, monkeypatch):
    registry.set_current_profile_id(7)
    calls: list[str] = []

    async def fake_remote(connector, full_name, server_tool, arguments):
        calls.append(server_tool)
        return {}

    monkeypatch.setattr(mcp, "_execute_remote", fake_remote)
    await mcp.call_tool(GDOCS_CREATE, {"title": "x"})

    resolution = await mcp.resolve_pending(7, "no, cancel that")
    assert resolution is not None and resolution.tool is None
    assert "NOT executed" in resolution.note
    assert calls == []


async def test_deferred_yes_does_not_execute(db, monkeypatch):
    registry.set_current_profile_id(7)
    calls: list[str] = []

    async def fake_remote(connector, full_name, server_tool, arguments):
        calls.append(server_tool)
        return {}

    monkeypatch.setattr(mcp, "_execute_remote", fake_remote)
    await mcp.call_tool(GDOCS_CREATE, {"title": "x"})

    resolution = await mcp.resolve_pending(7, "yes, but not now — tomorrow")
    assert resolution is not None and resolution.tool is None
    assert "NOT executed" in resolution.note
    assert calls == []


async def test_resolve_pending_without_pending_is_none(db):
    assert await mcp.resolve_pending(3, "yes") is None


async def test_confirmation_failure_is_reported_not_claimed(db, monkeypatch):
    registry.set_current_profile_id(9)
    try:

        async def boom(connector, full_name, server_tool, arguments):
            raise ConnectionError("server unreachable")

        monkeypatch.setattr(mcp, "_execute_remote", boom)
        await mcp.call_tool(GDOCS_CREATE, {"title": "x"})

        resolution = await mcp.resolve_pending(9, "yes")
        assert "failed with ConnectionError" in resolution.note
        assert '"error"' in resolution.note
    finally:
        registry.set_current_profile_id(None)


# --- registry routing ---------------------------------------------------------


async def test_registry_dispatches_mcp_tools(monkeypatch):
    async def fake_remote(connector, full_name, server_tool, arguments):
        return {"tool": GDRIVE_SEARCH, "content": "ok"}

    monkeypatch.setattr(mcp, "_execute_remote", fake_remote)
    result = await registry.call_tool(GDRIVE_SEARCH, {"query": "x", "reason": "user asked for their files"})
    assert result["content"] == "ok"


async def test_unknown_mcp_tool_is_a_model_facing_error():
    # both paths raise ValueError -> the loop converts it to a model-facing
    # tool failure ("do not pretend it worked"), never a 500
    with pytest.raises(ValueError, match="unknown MCP tool"):
        await mcp.call_tool("mcp__nope__tool", {})
    with pytest.raises(ValueError, match="unknown MCP tool"):
        await registry.call_tool("mcp__nope__tool", {})
    # a non-mcp unknown tool still gets the registry's own message
    with pytest.raises(ValueError, match="unknown tool"):
        await registry.call_tool("definitely_not_a_tool", {})


# --- discovery ----------------------------------------------------------------


async def test_refresh_tools_caches_converted_specs(db, monkeypatch):
    from sqlmodel import select

    async with db() as session:
        session.add(
            MCPAuthAccount(
                account="google",
                access_token="tok",
                expires_at=datetime.now(UTC) + timedelta(hours=1),
            )
        )
        await session.commit()

    fake = FakeSession(
        tools=[
            FakeMCPTool("files.list", "List Drive files."),
            FakeMCPTool("create_document", "Create a Google Doc."),
            FakeMCPTool("delete_forever", "Delete a file."),
        ]
    )
    # gdrive returns tools, gdocs (a different server!) returns none — proves
    # each connector discovers against its OWN endpoint, not a shared one
    _patch_session_per_connector(monkeypatch, {"gdrive": fake._tools, "gdocs": []})

    await mcp.refresh_tools(force=True)

    names = [s["function"]["name"] for s in mcp.list_specs()]
    assert "mcp__gdrive__files_list" in names
    assert "mcp__gdrive__create_document" in names
    assert "mcp__gdocs__files_list" not in names  # gdocs server returned nothing
    assert not any(n.startswith("mcp__gdocs__") for n in names)

    # sanitized spec name maps back to the ORIGINAL server tool name
    connector, server_tool = mcp.split_spec_name("mcp__gdrive__files_list")
    assert connector is not None and connector.name == "gdrive"
    assert server_tool == "files.list"

    # discovery never writes tokens
    async with db() as session:
        assert len((await session.exec(select(MCPAuthAccount))).all()) == 1


async def test_refresh_tools_skips_unconnected_connector(db, monkeypatch):
    opened: list[str] = []

    @asynccontextmanager
    async def fake_open(connector, headers):
        opened.append(connector.name)
        yield FakeSession()

    monkeypatch.setattr(mcp, "_open_session", fake_open)
    await mcp.refresh_tools(force=True)
    assert opened == []  # no token row -> no session, no network
    assert mcp.list_specs() == []


async def test_result_payload_shapes():
    text_block = SimpleNamespace(text="hello")
    ok = mcp._result_payload("mcp__gdrive__x", SimpleNamespace(content=[text_block], is_error=False, structured_content=None))
    assert ok == {"tool": "mcp__gdrive__x", "content": "hello"}

    err = mcp._result_payload("mcp__gdrive__x", SimpleNamespace(content=[text_block], is_error=True, structured_content=None))
    assert err["error"].startswith("mcp__gdrive__x failed")

    structured = mcp._result_payload(
        "mcp__gdrive__x",
        SimpleNamespace(content=[], is_error=False, structured_content={"rows": 2}),
    )
    assert structured["content"] == '{"rows": 2}'


# --- Google token lifecycle ---------------------------------------------------


async def test_expired_google_token_is_refreshed(db, monkeypatch):
    from sqlmodel import select

    async with db() as session:
        session.add(
            MCPAuthAccount(
                account="google",
                access_token="old",
                refresh_token="rt",
                expires_at=datetime.now(UTC) - timedelta(minutes=5),
            )
        )
        await session.commit()

    seen: dict = {}

    async def fake_exchange(payload):
        seen.update(payload)
        return {"access_token": "new", "expires_in": 3600, "scope": DRIVE_READONLY}

    monkeypatch.setattr(mcp, "_post_token_exchange", fake_exchange)

    token = await mcp._google_access_token()
    assert token == "new"
    assert seen["grant_type"] == "refresh_token"
    assert seen["refresh_token"] == "rt"

    async with db() as session:
        row = (await session.exec(select(MCPAuthAccount))).first()
    assert row.access_token == "new"
    assert row.refresh_token == "rt"  # refresh responses may omit it; stored one stays


async def test_expired_token_without_refresh_token_demands_reconnect(db):

    async with db() as session:
        session.add(
            MCPAuthAccount(
                account="google",
                access_token="old",
                refresh_token=None,
                expires_at=datetime.now(UTC) - timedelta(minutes=5),
            )
        )
        await session.commit()

    with pytest.raises(mcp.MCPAuthError, match="reconnect"):
        await mcp._google_access_token()


async def test_fresh_token_passes_through(db, monkeypatch):
    async with db() as session:
        session.add(
            MCPAuthAccount(
                account="google",
                access_token="fine",
                expires_at=datetime.now(UTC) + timedelta(hours=1),
            )
        )
        await session.commit()

    async def fake_exchange(payload):  # must never run
        raise AssertionError("fresh token must not trigger a refresh")

    monkeypatch.setattr(mcp, "_post_token_exchange", fake_exchange)
    assert await mcp._google_access_token() == "fine"


async def test_exchange_code_persists_and_invalidates_cache(db, monkeypatch):
    mcp._specs["gdrive"] = (0.0, [])

    async def fake_exchange(payload):
        assert payload["grant_type"] == "authorization_code"
        assert payload["code"] == "the-code"
        return {"access_token": "at", "refresh_token": "rt", "expires_in": 60, "scope": "a b"}

    monkeypatch.setattr(mcp, "_post_token_exchange", fake_exchange)

    result = await mcp.exchange_google_code("the-code")
    assert result == {"connected": True, "account": "google", "scopes": "a b"}
    assert "gdrive" not in mcp._specs  # discovery cache invalidated

    info = await mcp.google_token_info()
    assert info["connected"] is True and info["has_refresh_token"] is True


async def test_invalid_grant_surfaces_as_reconnect(db, monkeypatch):
    async def fake_exchange(payload):
        raise mcp.MCPAuthError("Google rejected the stored grant (expired or revoked). reconnect at /mcp/google/connect")

    monkeypatch.setattr(mcp, "_post_token_exchange", fake_exchange)
    with pytest.raises(mcp.MCPAuthError, match="reconnect"):
        await mcp.exchange_google_code("stale-code")
