"""Failure paths in tool dispatch and the agent loop.

A tool that raises, a model that hallucinates an argument, or a malformed
arguments blob must never abort the turn. The failure is handed to the model
as a `{"error": ...}` tool message so it can retry or report the gap honestly
(instead of a bare 500 / lost turn).
"""

import json
from types import SimpleNamespace

import pytest

from app.agent import loop
from app.tools import registry

OK_TOOL = "test_ok_tool_for_loop_error_tests"
BOOM_TOOL = "test_boom_tool_for_loop_error_tests"


@pytest.fixture
def ok_tool():
    """Registers a tool that records the kwargs it actually received."""
    received: list[dict] = []

    @registry.tool(
        name=OK_TOOL,
        description="Records the kwargs it was called with.",
        parameters={
            "type": "object",
            "properties": {"profile_id": {"type": "integer"}, "query": {"type": "string"}},
            "required": ["profile_id", "query"],
        },
    )
    async def ok(profile_id: int, query: str) -> dict:
        received.append({"profile_id": profile_id, "query": query})
        return {"echo": query}

    yield received
    registry._REGISTRY.pop(OK_TOOL, None)


@pytest.fixture
def boom_tool():
    """Registers a tool that always explodes."""

    @registry.tool(
        name=BOOM_TOOL,
        description="Always raises.",
        parameters={
            "type": "object",
            "properties": {"profile_id": {"type": "integer"}},
            "required": ["profile_id"],
        },
    )
    async def boom(profile_id: int) -> dict:
        raise RuntimeError("xpoz exploded")

    yield
    registry._REGISTRY.pop(BOOM_TOOL, None)


def _completion(content: str | None = None, tool_calls: list | None = None) -> SimpleNamespace:
    message = SimpleNamespace(content=content, tool_calls=tool_calls)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def _tool_call(name: str, arguments: str) -> SimpleNamespace:
    return SimpleNamespace(
        id="call_1",
        type="function",
        function=SimpleNamespace(name=name, arguments=arguments),
    )


def _tool_messages(captured: dict) -> list[dict]:
    """The tool messages the model saw — they only exist from the *second* call on."""
    for batch in captured["model_messages"]:
        tools = [m for m in batch if m.get("role") == "tool"]
        if tools:
            return tools
    return []


@pytest.fixture
def turn_harness(monkeypatch):
    """Patch everything the loop touches outside its own logic; return the capture dict."""
    captured: dict = {"saved": [], "model_messages": [], "completions": []}

    async def fake_save(profile_id, role, content, tool_name=None, tool_calls=None, reason=None, tools_used=None):
        captured["saved"].append({"role": role, "content": content, "reason": reason, "tools_used": tools_used})

    async def fake_history(profile_id):
        return []

    async def fake_profile(profile_id):
        return None

    async def fake_completion(messages, tools, effort=None):
        captured["model_messages"].append([dict(m) for m in messages])
        return captured["completions"][len(captured["model_messages"]) - 1]

    monkeypatch.setattr(loop, "_save_message", fake_save)
    monkeypatch.setattr(loop, "_load_history", fake_history)
    monkeypatch.setattr(loop, "_load_profile", fake_profile)
    monkeypatch.setattr(loop, "build_system_prompt", lambda *a, **k: "system")
    monkeypatch.setattr(loop, "get_profile_summary", lambda *a, **k: "")
    monkeypatch.setattr(loop, "chat_completion_with_fallback", fake_completion)
    monkeypatch.setattr(loop, "_schedule_memory_extraction", lambda *a, **k: None)
    # The classification row is written fire-and-forget into the real DB;
    # keep the turn hermetic (same pattern as memory extraction).
    monkeypatch.setattr(loop, "_schedule_classification", lambda *a, **k: None)

    async def fake_refresh_tools(force: bool = False):
        return None

    # MCP discovery would query the DB for connector tokens; keep the turn hermetic.
    monkeypatch.setattr(loop.mcp_service, "refresh_tools", fake_refresh_tools)
    return captured


# --- registry-level argument hygiene ---------------------------------------


async def test_call_tool_drops_undeclared_arguments(ok_tool):
    registry.set_current_profile_id(None)
    result = await registry.call_tool(
        OK_TOOL, {"profile_id": 7, "query": "hooks", "url": "https://x.com/someone", "reason": "user asked for hooks"}
    )
    assert result == {"echo": "hooks"}
    # the hallucinated `url` kwarg never reached the function
    assert ok_tool == [{"profile_id": 7, "query": "hooks"}]


async def test_call_tool_missing_required_raises_model_facing_value_error(ok_tool):
    registry.set_current_profile_id(None)
    with pytest.raises(ValueError) as excinfo:
        await registry.call_tool(OK_TOOL, {"profile_id": 7, "reason": "user asked for a recon"})
    message = str(excinfo.value)
    assert "missing required argument(s): query" in message
    assert "Declared parameters" in message


# --- loop-level: no failure aborts the turn --------------------------------


async def test_extra_argument_is_dropped_and_turn_survives(turn_harness, ok_tool):
    turn_harness["completions"] = [
        _completion(
            tool_calls=[
                _tool_call(
                    OK_TOOL,
                    json.dumps(
                        {
                            "profile_id": 1,
                            "query": "hooks",
                            "url": "https://x.com/someone",
                            "reason": "user asked for hooks",
                        }
                    ),
                )
            ]
        ),
        _completion(content="All set."),
    ]

    result = await loop._run_agent_loop(1, "do a fresh recon")

    assert result.content == "All set."
    assert result.tool_calls_made == [OK_TOOL]
    assert ok_tool == [{"profile_id": 1, "query": "hooks"}]

    tool_msgs = _tool_messages(turn_harness)
    assert len(tool_msgs) == 1
    payload = json.loads(tool_msgs[0]["content"])
    assert "error" not in payload


async def test_raising_tool_is_handed_to_the_model(turn_harness, boom_tool):
    turn_harness["completions"] = [
        _completion(
            tool_calls=[
                _tool_call(BOOM_TOOL, json.dumps({"profile_id": 1, "reason": "user asked for a recon"}))
            ]
        ),
        _completion(content="That failed — here is what I know instead."),
    ]

    result = await loop._run_agent_loop(1, "scan the niche")

    assert result.content == "That failed — here is what I know instead."
    assert result.tool_calls_made == [BOOM_TOOL]

    payload = json.loads(_tool_messages(turn_harness)[0]["content"])
    assert "error" in payload
    assert "RuntimeError" in payload["error"]
    assert "xpoz exploded" in payload["error"]


async def test_malformed_tool_arguments_do_not_abort_turn(turn_harness, ok_tool):
    turn_harness["completions"] = [
        _completion(tool_calls=[_tool_call(OK_TOOL, '{"profile_id": 1, "query": ')]),
        _completion(content="Recovered."),
    ]

    result = await loop._run_agent_loop(1, "hello there")

    assert result.content == "Recovered."
    assert ok_tool == []  # never dispatched with garbage

    payload = json.loads(_tool_messages(turn_harness)[0]["content"])
    assert "not valid JSON object text" in payload["error"]


async def test_missing_required_argument_is_reported_to_model(turn_harness, ok_tool):
    turn_harness["completions"] = [
        _completion(
            tool_calls=[_tool_call(OK_TOOL, json.dumps({"profile_id": 1, "reason": "user asked for a recon"}))]
        ),
        _completion(content="Let me try that again."),
    ]

    result = await loop._run_agent_loop(1, "recon please")

    assert result.content == "Let me try that again."
    assert ok_tool == []

    payload = json.loads(_tool_messages(turn_harness)[0]["content"])
    assert "missing required argument" in payload["error"]
