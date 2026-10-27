"""Request-size budget: _fit_messages keeps the turn under the provider wall.

Groq's qwen3.8-27b rejects requests over ~7,000 input tokens (measured
2026-10-21). The loop estimates the assembled request (chars/3.5) against
MAX_REQUEST_TOKENS and trims with a ladder: drop oldest history -> shrink
older tool-group contents -> drop oldest whole tool groups. The system prompt,
the resolution note, the current user message, and the newest tool group are
never dropped; still-over-budget requests are sent as-is (the model fallback
chain may accept them).
"""

import json
from types import SimpleNamespace

import pytest

from app.agent import loop


def _msg(role: str, content: str, tool_calls: list | None = None) -> dict:
    m: dict = {"role": role, "content": content}
    if tool_calls is not None:
        m["tool_calls"] = tool_calls
    return m


def _tool_group(call_id: str, payload_chars: int) -> list[dict]:
    """One assistant tool_calls message + its tool response."""
    return [
        _msg("assistant", None, tool_calls=[{"id": call_id}]),
        _msg("tool", "x" * payload_chars),
    ]


# --- _estimate_tokens ---------------------------------------------------------


def test_estimate_tokens_is_chars_over_3_5():
    assert loop._estimate_tokens("") == 0
    assert loop._estimate_tokens("a" * 35) == 10
    assert loop._estimate_tokens("a" * 36) == 11  # ceil, never under-counts


def test_message_estimate_includes_tool_calls_payload():
    plain = loop._message_token_estimate(_msg("assistant", "hi"))
    with_calls = loop._message_token_estimate(
        _msg("assistant", "hi", tool_calls=[{"id": "c1"}])
    )
    assert with_calls > plain


# --- rung 1: drop oldest history ---------------------------------------------


def test_under_budget_passes_through_untouched():
    system = _msg("system", "sys")
    history = [_msg("user", "old"), _msg("assistant", "reply"), _msg("user", "current")]
    messages = [system, *history]
    result = loop._fit_messages(messages, 1, 3, tools_tokens=0)
    assert messages == [system, *history]
    assert result == 3


def test_oldest_history_dropped_first_system_and_current_kept():
    system = _msg("system", "s" * 7000)  # ~2,000 est tokens, protected
    oldest = _msg("user", "a" * 21_000)  # 6,000 est
    middle = _msg("assistant", "b" * 3500)  # 1,000 est
    current = _msg("user", "the current ask")
    messages = [system, oldest, middle, current]
    # total ~9,000 > 6,700 -> drop oldest only
    result = loop._fit_messages(messages, 1, 3, tools_tokens=0)
    assert messages == [system, middle, current]
    assert result == 2  # user index shifted left with the drop


def test_system_and_resolution_note_never_dropped():
    system = _msg("system", "s" * 7000)
    note = _msg("system", "pending write: none")
    current = _msg("user", "u" * 70_000)  # single over-budget ask: nothing droppable
    messages = [system, note, current]
    loop._fit_messages(messages, 2, 2, tools_tokens=0)
    assert messages == [system, note, current]


def test_current_user_message_survives_even_when_over_budget():
    system = _msg("system", "sys")
    oldest = _msg("user", "a" * 21_000)
    current = _msg("user", "u" * 24_000)  # ~6,900 est alone: still never dropped
    messages = [system, oldest, current]
    loop._fit_messages(messages, 1, 2, tools_tokens=0)
    assert messages == [system, current]


def test_empty_history_is_safe():
    system = _msg("system", "s" * 70_000)  # over budget with nothing droppable
    messages = [system]
    result = loop._fit_messages(messages, 1, 1, tools_tokens=0)
    assert messages == [system]
    assert result == 1


# --- rungs 2/3: tool groups ---------------------------------------------------


def test_older_tool_groups_shrink_before_anything_is_dropped():
    system = _msg("system", "s" * 3500)  # ~1,000 est
    current = _msg("user", "current ask")
    group_old = _tool_group("c1", 4000)
    group_new = _tool_group("c2", 4000)
    messages = [system, current, *group_old, *group_new]
    # ~3,310 est of messages vs budget 2,700 (=6,700-4,000): shrink fixes it
    loop._fit_messages(messages, 1, 1, tools_tokens=4000)
    assert len(messages[3]["content"]) <= loop.OLD_TOOL_CONTEXT_CHAR_LIMIT + 40
    assert "older tool result trimmed" in messages[3]["content"]
    assert messages[5]["content"] == "x" * 4000  # newest group untouched
    assert len(messages) == 6  # nothing dropped


def test_oldest_tool_group_dropped_whole_when_shrink_is_not_enough():
    system = _msg("system", "s" * 3500)
    current = _msg("user", "current ask")
    group_old = _tool_group("c1", 4000)
    group_mid = _tool_group("c2", 4000)
    group_new = _tool_group("c3", 4000)
    messages = [system, current, *group_old, *group_mid, *group_new]
    loop._fit_messages(messages, 1, 1, tools_tokens=4000)
    # group 1 (shrunk) still didn't fit -> dropped whole: assistant + tool together
    assert len(messages) == 6  # system, current, mid, new
    assert messages[2]["tool_calls"] is not None  # mid group's assistant kept
    assert messages[3]["content"].startswith("x")
    assert messages[5]["content"] == "x" * 4000  # newest untouched
    # no orphan: every remaining tool response has its assistant tool_calls before it
    for i, m in enumerate(messages):
        if m["role"] == "tool":
            assert messages[i - 1].get("tool_calls")


def test_newest_tool_group_never_dropped_even_when_alone_over_budget():
    system = _msg("system", "s" * 20_000)  # everything protected, way over
    current = _msg("user", "current ask")
    group = _tool_group("c1", 4000)
    messages = [system, current, *group]
    loop._fit_messages(messages, 1, 1, tools_tokens=3500)
    assert len(messages) == 4
    assert messages[3]["content"] == "x" * 4000


# --- integration through _agent_turn ------------------------------------------


@pytest.fixture
def budget_turn(monkeypatch):
    captured: dict = {"model_messages": [], "history": []}

    async def fake_save(*a, **k):
        return None

    async def fake_history(profile_id):
        return list(captured["history"])

    async def fake_profile(profile_id):
        return None

    async def fake_completion(messages, tools, effort=None):
        captured["model_messages"].append([dict(m) for m in messages])
        message = SimpleNamespace(content="All set — nothing else to report.", tool_calls=None)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    monkeypatch.setattr(loop, "_save_message", fake_save)
    monkeypatch.setattr(loop, "_load_history", fake_history)
    monkeypatch.setattr(loop, "_load_profile", fake_profile)
    monkeypatch.setattr(loop, "build_system_prompt", lambda *a, **k: "system prompt here")
    monkeypatch.setattr(loop, "get_profile_summary", lambda *a, **k: "")
    monkeypatch.setattr(loop, "chat_completion_with_fallback", fake_completion)
    monkeypatch.setattr(loop, "_schedule_memory_extraction", lambda *a, **k: None)
    # The classification row is written fire-and-forget into the real DB;
    # keep the turn hermetic (same pattern as memory extraction).
    monkeypatch.setattr(loop, "_schedule_classification", lambda *a, **k: None)

    async def fake_refresh_tools(force: bool = False):
        return None

    monkeypatch.setattr(loop.mcp_service, "refresh_tools", fake_refresh_tools)
    return captured


async def test_agent_turn_trims_history_to_budget(budget_turn):
    # 10 fat history messages (~5,700 est tokens) + full tool specs (~2,900 est)
    # would bust qwen's 7,000 wall; the turn must fit under MAX_REQUEST_TOKENS.
    def fat(tag: str) -> dict:
        return {"role": "user", "content": f"{tag} " + "w" * 3000}

    budget_turn["history"] = [fat(f"msg{i}") for i in range(9)] + [
        {"role": "user", "content": "current short ask"}
    ]

    result = await loop._agent_turn(1, "current short ask", "handle", "Name")

    assert result.content.startswith("All set")
    sent = budget_turn["model_messages"][0]
    assert sent[0]["content"] == "system prompt here"  # system first, protected
    assert sent[-1]["content"] == "current short ask"  # current ask last, protected
    assert len(sent) < len(budget_turn["history"]) + 1  # oldest history dropped
    total = sum(loop._message_token_estimate(m) for m in sent)
    tools = loop.tool_registry.list_tool_specs()
    total += loop._estimate_tokens(json.dumps(tools))
    assert total <= loop.MAX_REQUEST_TOKENS + 200  # within rounding of the wall
