"""Registry: reason injection and validation, profile pinning, cache, cost filter, MCP."""

from __future__ import annotations

import pytest

from lumi_ai.ports import McpCallResult, McpToolSpec
from lumi_ai.tests.fakes import FakeMcp
from lumi_ai.tools.registry import ToolContext, ToolRegistry, ToolSpec, validate_reason

CTX = ToolContext(profile_id=2)


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def make_registry(clock: Clock | None = None, mcp: FakeMcp | None = None):
    calls: list[dict] = []

    async def echo(ctx: ToolContext, **kwargs):
        calls.append({"profile": ctx.profile_id, **kwargs})
        return {"ok": True, **kwargs}

    async def failing(ctx: ToolContext, **kwargs):
        calls.append({"fail": True})
        return {"error": "upstream down"}

    registry = ToolRegistry(mcp, clock=clock or Clock())
    registry.register(
        ToolSpec(
            name="free_tool",
            description="d",
            parameters={
                "type": "object",
                "properties": {
                    "profile_id": {"type": "integer"},
                    "q": {"type": "string"},
                },
                "required": ["profile_id", "q"],
            },
            handler=echo,
        )
    )
    registry.register(
        ToolSpec(
            name="paid_tool",
            description="d",
            parameters={"type": "object", "properties": {"q": {"type": "string"}}},
            handler=echo,
            cost="credits",
        )
    )
    registry.register(
        ToolSpec(
            name="flaky_tool",
            description="d",
            parameters={"type": "object", "properties": {}},
            handler=failing,
            cost="credits",
        )
    )
    registry.register(
        ToolSpec(
            name="write_tool",
            description="d",
            parameters={"type": "object", "properties": {}},
            handler=echo,
            cost="write",
        )
    )
    return registry, calls


def test_every_emitted_spec_requires_reason_and_the_original_is_untouched():
    registry, _ = make_registry()
    specs = registry.list_specs()
    for spec in specs:
        params = spec["function"]["parameters"]
        assert "reason" in params["required"]
        assert "reason" in params["properties"]
    assert "reason" not in registry.get("free_tool").parameters["properties"]  # type: ignore[union-attr]


def test_cost_and_name_filters_are_anded():
    registry, _ = make_registry()

    def names(**kw):
        return {s["function"]["name"] for s in registry.list_specs(**kw)}

    assert names(allowed_costs={"free"}) == {"free_tool"}
    assert names(
        allowed_costs={"free", "credits"}, allowed_names={"paid_tool", "write_tool"}
    ) == {"paid_tool"}
    assert names(allowed_names=set()) == set()
    assert names() == {"free_tool", "paid_tool", "flaky_tool", "write_tool"}


async def test_missing_reason_is_a_model_readable_error():
    registry, calls = make_registry()
    with pytest.raises(ValueError, match="missing required argument: reason"):
        await registry.call(CTX, "free_tool", {"q": "x"})
    assert calls == []


@pytest.mark.parametrize("name", ["paid_tool", "write_tool"])
async def test_spending_tools_reject_a_reason_that_restates_the_name(name):
    registry, calls = make_registry()
    with pytest.raises(ValueError, match="not a reason"):
        await registry.call(CTX, name, {"reason": "Call the " + name.replace("_", " ")})
    assert calls == []


def test_free_tools_accept_a_terse_reason():
    assert validate_reason("free_tool", "free", "free tool") == "free tool"


async def test_profile_id_is_pinned_to_the_turn_even_if_the_model_sends_another():
    registry, calls = make_registry()
    await registry.call(CTX, "free_tool", {"reason": "r", "q": "x", "profile_id": 99})
    await registry.call(CTX, "free_tool", {"reason": "r", "q": "y", "profile_id": None})
    assert [c["profile"] for c in calls] == [2, 2]
    assert all(
        "profile_id" not in c for c in calls
    )  # handler reads ctx, not an argument


async def test_missing_required_and_unknown_arguments():
    registry, calls = make_registry()
    with pytest.raises(ValueError, match="missing required argument\\(s\\): q"):
        await registry.call(CTX, "free_tool", {"reason": "r"})
    out = await registry.call(CTX, "free_tool", {"reason": "r", "q": "x", "bogus": 1})
    assert out == {"ok": True, "q": "x"}
    assert len(calls) == 1


async def test_unknown_tool():
    registry, _ = make_registry()
    with pytest.raises(ValueError, match="unknown tool: nope"):
        await registry.call(CTX, "nope", {"reason": "r"})


async def test_credit_tools_are_cached_per_profile_and_expire():
    clock = Clock()
    registry, calls = make_registry(clock)
    a = {"reason": "look it up", "q": "x"}
    first = await registry.call(CTX, "paid_tool", dict(a))
    second = await registry.call(CTX, "paid_tool", dict(a))
    assert len(calls) == 1
    assert "cache" not in first and second["cache"].startswith("cached")
    # another profile never sees it
    await registry.call(ToolContext(profile_id=3), "paid_tool", dict(a))
    assert len(calls) == 2
    # a different reason alone does not change the key
    await registry.call(CTX, "paid_tool", {"reason": "other words", "q": "x"})
    assert len(calls) == 2
    clock.t += 901
    await registry.call(CTX, "paid_tool", dict(a))
    assert len(calls) == 3


async def test_failures_are_not_cached_and_free_tools_never_are():
    registry, calls = make_registry()
    for _ in range(2):
        await registry.call(CTX, "flaky_tool", {"reason": "try the scan"})
    assert len(calls) == 2
    for _ in range(2):
        await registry.call(CTX, "free_tool", {"reason": "r", "q": "x"})
    assert len(calls) == 4


async def test_cached_result_cannot_be_mutated_by_the_caller():
    registry, _ = make_registry()
    first = await registry.call(CTX, "paid_tool", {"reason": "look it up", "q": "x"})
    first["q"] = "tampered"
    second = await registry.call(CTX, "paid_tool", {"reason": "look it up", "q": "x"})
    assert second["q"] == "x"


async def test_tool_names_cannot_collide_or_use_the_mcp_prefix():
    registry, _ = make_registry()
    spec = registry.get("free_tool")
    assert spec is not None
    with pytest.raises(ValueError, match="already registered"):
        registry.register(spec)
    with pytest.raises(ValueError, match="reserved for MCP"):
        registry.register(ToolSpec("mcp__x__y", "d", {"type": "object"}, spec.handler))
    with pytest.raises(ValueError, match="unknown cost"):
        ToolSpec("t", "d", {}, spec.handler, cost="free-ish")  # type: ignore[arg-type]


# --- MCP ------------------------------------------------------------------------------


def drive_spec(cost="free"):
    return McpToolSpec(
        name="mcp__drive__search",
        description="Search Drive",
        parameters={"type": "object", "properties": {"q": {"type": "string"}}},
        cost=cost,  # type: ignore[arg-type]
    )


async def test_mcp_specs_are_listed_filtered_and_called_through_the_gateway():
    mcp = FakeMcp(
        [drive_spec()],
        McpCallResult(status="ok", payload={"files": ["a"]}, summary="1 file"),
    )
    registry, _ = make_registry(mcp=mcp)
    specs = await registry.mcp_specs(2)
    emitted = {
        s["function"]["name"] for s in registry.list_specs({"free"}, None, specs)
    }
    assert emitted == {"free_tool", "mcp__drive__search"}
    out = await registry.call(
        CTX, "mcp__drive__search", {"reason": "find the brief", "q": "x"}, specs
    )
    assert out == {"status": "ok", "files": ["a"], "summary": "1 file"}
    assert mcp.calls == [
        (2, "mcp__drive__search", {"q": "x"})
    ]  # reason never reaches the connector
    assert registry.cost_of("mcp__drive__search", specs) == "free"


async def test_mcp_call_without_connector_or_reason_is_refused():
    mcp = FakeMcp([drive_spec()])
    registry, _ = make_registry(mcp=mcp)
    specs = await registry.mcp_specs(2)
    with pytest.raises(ValueError, match="reason"):
        await registry.call(CTX, "mcp__drive__search", {"q": "x"}, specs)
    with pytest.raises(ValueError, match="not connected"):
        await registry.call(CTX, "mcp__gmail__send", {"reason": "mail it"}, specs)
    assert mcp.calls == []


async def test_mcp_discovery_failure_means_no_connector_tools_not_a_dead_turn():
    mcp = FakeMcp([drive_spec()])
    mcp.fail_list = True
    registry, _ = make_registry(mcp=mcp)
    assert await registry.mcp_specs(2) == {}
    assert await ToolRegistry().mcp_specs(2) == {}
