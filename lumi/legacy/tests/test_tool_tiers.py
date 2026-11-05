"""L13 item 3/4: per-tool cost tiers, side-effect tags, TTL cache, required `reason`."""

import pytest

from app.services import mcp as mcp_service
from app.tools import registry

CREDITS_TOOL = "test_tier_credits_probe"
LLM_TOOL = "test_tier_llm_probe"
FREE_TOOL = "test_tier_free_probe"
WRITE_TOOL = "test_tier_write_probe"
ERR_TOOL = "test_tier_error_probe"
TOUCHY_TOOL = "test_tier_touchy_probe"
OURS = (CREDITS_TOOL, LLM_TOOL, FREE_TOOL, WRITE_TOOL, ERR_TOOL, TOUCHY_TOOL)

# The locked tier table for all 20 native tools (Phase C design).
NATIVE_TIERS = {
    # write
    "submit_action": "write",
    "connect_account": "write",
    # credits
    "check_niche_trends": "credits",
    "discover_and_extract_niche_frameworks": "credits",
    "get_peer_advice": "credits",
    "backfill_posts": "credits",
    # llm
    "check_trending": "llm",
    "repurpose_caption": "llm",
    "extract_voice_profile": "llm",
    # free (the rest)
    "dismiss_alert": "free",
    "get_user_activity": "free",
    "get_analytics": "free",
    "start_listening": "free",
    "stop_listening": "free",
    "remember": "free",
    "recall_memory": "free",
    "get_posts": "free",
    "save_user_request": "free",
    "get_voice_profile": "free",
    "answer_style_questions": "free",
}
NATIVE_NAMES = frozenset(NATIVE_TIERS)


def _clear_our_cache():
    for key in list(registry._result_cache):
        if key[1] in OURS:
            registry._result_cache.pop(key, None)


@pytest.fixture
def tier_tools():
    calls = dict.fromkeys(OURS, 0)

    @registry.tool(
        name=CREDITS_TOOL,
        description="Credits-tier probe.",
        parameters={"type": "object", "properties": {}},
        cost="credits",
    )
    async def credits_probe() -> dict:
        calls[CREDITS_TOOL] += 1
        return {"runs": calls[CREDITS_TOOL]}

    @registry.tool(
        name=LLM_TOOL,
        description="LLM-tier probe.",
        parameters={"type": "object", "properties": {}},
        cost="llm",
    )
    async def llm_probe() -> dict:
        calls[LLM_TOOL] += 1
        return {"runs": calls[LLM_TOOL]}

    @registry.tool(
        name=FREE_TOOL,
        description="Free-tier probe.",
        parameters={"type": "object", "properties": {}},
    )
    async def free_probe() -> dict:
        calls[FREE_TOOL] += 1
        return {"runs": calls[FREE_TOOL]}

    @registry.tool(
        name=WRITE_TOOL,
        description="Write-tier probe.",
        parameters={"type": "object", "properties": {}},
        cost="write",
    )
    async def write_probe() -> dict:
        calls[WRITE_TOOL] += 1
        return {"runs": calls[WRITE_TOOL]}

    @registry.tool(
        name=ERR_TOOL,
        description="Always-failing probe (result dict carries an error).",
        parameters={"type": "object", "properties": {}},
        cost="llm",
    )
    async def err_probe() -> dict:
        calls[ERR_TOOL] += 1
        return {"error": "boom"}

    @registry.tool(
        name=TOUCHY_TOOL,
        description="Declares one real argument.",
        parameters={
            "type": "object",
            "properties": {"value": {"type": "integer"}},
            "required": ["value"],
        },
    )
    async def touchy_probe(value: int) -> dict:
        calls[TOUCHY_TOOL] += 1
        return {"value": value}

    _clear_our_cache()
    yield calls
    for name in OURS:
        registry._REGISTRY.pop(name, None)
    _clear_our_cache()
    registry.set_current_profile_id(None)


# --- tier table -----------------------------------------------------------------


def test_native_tool_tier_table_is_locked():
    assert len(NATIVE_TIERS) == 20
    for name, cost in NATIVE_TIERS.items():
        spec = registry.get_tool(name)
        assert spec is not None, f"{name} is not registered"
        assert spec.cost == cost, f"{name}: expected {cost}, got {spec.cost}"
        assert registry.get_cost(name) == cost


def test_cache_ttl_defaults_follow_the_tier():
    assert registry.DEFAULT_TTL_BY_COST == {"credits": 900.0, "llm": 600.0}
    for name, cost in NATIVE_TIERS.items():
        spec = registry.get_tool(name)
        expected = {"credits": 900.0, "llm": 600.0}.get(cost, 0.0)
        assert spec.cache_ttl == expected, f"{name} ({cost})"


def test_side_effect_declarations():
    expect = {
        "connect_account": "none",  # mints an auth URL only; DB write is in the OAuth callback
        "get_posts": "none",
        "recall_memory": "none",
        "get_user_activity": "none",
        "get_voice_profile": "none",
        "remember": "writes_index",
        "submit_action": "writes_db",
        "dismiss_alert": "writes_db",
        "get_analytics": "writes_db",
        "save_user_request": "writes_db",
    }
    for name, side_effects in expect.items():
        assert registry.get_tool(name).side_effects == side_effects, name


def test_get_cost_unknown_returns_none():
    assert registry.get_cost("definitely_not_a_real_tool") is None


def test_decorator_rejects_invalid_enums_at_import_time():
    with pytest.raises(ValueError, match="unknown cost"):
        registry.tool(
            name="test_tier_bogus_cost",
            description="x",
            parameters={"type": "object", "properties": {}},
            cost="expensive",
        )
    with pytest.raises(ValueError, match="unknown side_effects"):
        registry.tool(
            name="test_tier_bogus_side_effect",
            description="x",
            parameters={"type": "object", "properties": {}},
            side_effects="mutates_stuff",
        )


# --- reason injection (emitted vs stored) ---------------------------------------


def test_reason_injected_into_emitted_but_not_stored(tier_tools):
    stored = registry.get_tool(FREE_TOOL).parameters
    assert "reason" not in (stored.get("properties") or {})
    assert "reason" not in (stored.get("required") or [])

    emitted = registry.list_tool_specs(allowed_names=[FREE_TOOL])
    params = emitted[0]["function"]["parameters"]
    assert "reason" in params["properties"]
    assert "reason" in params["required"]
    # original required entries survive
    stored_required = stored.get("required") or []
    assert set(stored_required) <= set(params["required"])


def test_list_tool_specs_filters_by_cost(monkeypatch, tier_tools):
    monkeypatch.setattr(mcp_service, "list_specs", list)
    names = {s["function"]["name"] for s in registry.list_tool_specs(allowed_costs={"credits"})}
    expected = {n for n, c in NATIVE_TIERS.items() if c == "credits"}
    expected.add(CREDITS_TOOL)  # the fixture probe is credits-tier too
    assert names == expected
    # free-tier probe must not leak into a credits-only toolset
    assert FREE_TOOL not in names


def test_list_tool_specs_filters_by_names_and_and_combines(monkeypatch, tier_tools):
    monkeypatch.setattr(mcp_service, "list_specs", list)
    names = {s["function"]["name"] for s in registry.list_tool_specs(allowed_names=[FREE_TOOL])}
    assert names == {FREE_TOOL}

    # cost + name must BOTH match
    both = registry.list_tool_specs(allowed_costs={"write"}, allowed_names=[FREE_TOOL])
    assert both == []

    # an empty collection yields no tools at all
    assert registry.list_tool_specs(allowed_costs=set(), allowed_names=set()) == []


# --- reason validation ----------------------------------------------------------


async def test_missing_reason_is_rejected_with_retry_hint(tier_tools):
    with pytest.raises(ValueError, match="missing required argument: reason"):
        await registry.call_tool(FREE_TOOL, {})
    with pytest.raises(ValueError, match="Retry with the reason filled in"):
        await registry.call_tool(FREE_TOOL, {"reason": "   "})
    assert tier_tools[FREE_TOOL] == 0


async def test_tool_name_only_reason_rejected_for_credits_and_write(tier_tools):
    with pytest.raises(ValueError, match="restating the tool's name"):
        await registry.call_tool(CREDITS_TOOL, {"reason": "test_tier_credits_probe"})
    with pytest.raises(ValueError, match="restating the tool's name"):
        await registry.call_tool(WRITE_TOOL, {"reason": "run the test tier write probe tool"})
    assert tier_tools[CREDITS_TOOL] == 0
    assert tier_tools[WRITE_TOOL] == 0

    # a real why is accepted
    result = await registry.call_tool(
        CREDITS_TOOL, {"reason": "user asked to compare paid tools before spending credits"}
    )
    assert result == {"runs": 1}


async def test_tool_name_only_reason_accepted_for_free(tier_tools):
    # vacuous but allowed: free tools only need a non-empty reason
    result = await registry.call_tool(FREE_TOOL, {"reason": FREE_TOOL})
    assert result == {"runs": 1}


async def test_reason_reaches_the_audit_span_not_the_function(tier_tools):
    # `reason` is popped before dispatch — if it leaked into kwargs the call
    # would raise TypeError, and the declared argument still arrives intact.
    result = await registry.call_tool(TOUCHY_TOOL, {"value": 3, "reason": "user asked for a number"})
    assert result == {"value": 3}
    assert tier_tools[TOUCHY_TOOL] == 1


# --- TTL cache ------------------------------------------------------------------


async def test_credits_tool_result_is_cached_with_age_marker(tier_tools):
    first = await registry.call_tool(CREDITS_TOOL, {"reason": "user asked for a scan"})
    assert "cache" not in first

    second = await registry.call_tool(CREDITS_TOOL, {"reason": "user asked for a scan again"})
    assert second["runs"] == 1  # served from cache, function not re-executed
    assert second["cache"].startswith("cached, ")
    assert "cache_age_seconds" in second
    assert tier_tools[CREDITS_TOOL] == 1


async def test_cached_result_is_a_deepcopy(tier_tools):
    first = await registry.call_tool(CREDITS_TOOL, {"reason": "user asked for a scan"})
    first["injected_by_caller"] = True  # mutating a returned result must not poison the cache

    second = await registry.call_tool(CREDITS_TOOL, {"reason": "user asked for a scan"})
    assert "injected_by_caller" not in second
    assert second["runs"] == 1


async def test_error_results_are_never_cached(tier_tools):
    first = await registry.call_tool(ERR_TOOL, {"reason": "probing the failure path"})
    assert "error" in first
    second = await registry.call_tool(ERR_TOOL, {"reason": "probing the failure path again"})
    assert "cache" not in second
    assert tier_tools[ERR_TOOL] == 2


async def test_free_and_write_tools_never_cache(tier_tools):
    await registry.call_tool(FREE_TOOL, {"reason": "user asked for a listing"})
    await registry.call_tool(FREE_TOOL, {"reason": "user asked for a listing again"})
    assert tier_tools[FREE_TOOL] == 2

    await registry.call_tool(WRITE_TOOL, {"reason": "user confirmed the write"})
    await registry.call_tool(WRITE_TOOL, {"reason": "user confirmed the write again"})
    assert tier_tools[WRITE_TOOL] == 2


async def test_cache_is_scoped_per_profile(tier_tools):
    registry.set_current_profile_id(1)
    await registry.call_tool(CREDITS_TOOL, {"reason": "user asked for a scan"})
    registry.set_current_profile_id(2)
    await registry.call_tool(CREDITS_TOOL, {"reason": "user asked for a scan"})
    assert tier_tools[CREDITS_TOOL] == 2  # different profile -> different cache entry


async def test_explicit_zero_ttl_disables_cache_for_a_credits_tool(tier_tools):
    name = "test_tier_uncached_credits"

    @registry.tool(
        name=name,
        description="Credits tool that opts out of caching.",
        parameters={"type": "object", "properties": {}},
        cost="credits",
        cache_ttl=0,
    )
    async def uncached_credits() -> dict:
        tier_tools.setdefault("_uncached_runs", 0)
        tier_tools["_uncached_runs"] += 1
        return {"runs": tier_tools["_uncached_runs"]}

    try:
        assert registry.get_tool(name).cache_ttl == 0.0
        await registry.call_tool(name, {"reason": "user asked for a fresh scan"})
        await registry.call_tool(name, {"reason": "user asked for a fresh scan again"})
        assert tier_tools["_uncached_runs"] == 2
    finally:
        registry._REGISTRY.pop(name, None)
