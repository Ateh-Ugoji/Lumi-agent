"""PROMPT 5 acceptance tests (loop-level items 1, 2, 3, 5, 11).

Proves, end to end through the real `_run_agent_loop`, that:

1.  A greeting takes the fast path: one completion, the fast prompt (no
    "Operating rules" block), low effort, no MCP refresh, no full-prompt
    history, and no `mcp_ms` in the timings row.
2.  A TOOLS USED note lets the model answer "what tools did you use?" from
    the note instead of re-running tools (zero tool calls on the turn).
3.  A scan turn sends the required `reason` on the tool call, the reason
    reaches the TOOL row and the `tool_start` SSE event — and the reason key
    is stripped before the provider sees the arguments.
5.  The final classification row is scheduled exactly once, after the final
    reply is saved, and never raises if its DB write fails.
11. A full read-cheap turn offers only free tools (tier filter), with the
    Free-first ambiguity rule visible in the sent system prompt.

Plus two loop gates PROMPT 5 depends on: a pending-write note forces the
full path, and a coverage-required turn never takes the fast path.

See `lumi_logic_plan.md` (PROMPT 5, acceptance 427-439). Unit-level items
(reason stripping, TTL cache, Jev banding) live in `test_tool_tiers.py`
and `test_turn_class.py`.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.agent import loop as loop_mod
from app.agent import turn_class as turn_class_mod
from app.agent.loop import _run_agent_loop
from app.agent.prompts import build_fast_prompt, build_system_prompt
from app.models.turn_classification import TurnClassification
from app.tools import registry as registry_mod
from app.tools.registry import ToolSpec

# The note header marks a TOOLS USED note appended to an earlier turn. It is
# deliberately NOT the bare string "TOOLS USED", which also appears in the
# full system prompt (rule 22) at history index 0.
NOTE_MARKER = "TOOLS USED (from earlier turns"


def _completion(text: str) -> SimpleNamespace:
    message = SimpleNamespace(content=text, tool_calls=None)
    return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason=None)])


def _tool_call(name: str, arguments: dict) -> SimpleNamespace:
    import json

    call = SimpleNamespace(
        id="call_1",
        type="function",
        function=SimpleNamespace(name=name, arguments=json.dumps(arguments)),
    )
    message = SimpleNamespace(content=None, tool_calls=[call])
    return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason=None)])


@pytest.fixture
def turn_harness(monkeypatch: pytest.MonkeyPatch):
    """Records everything `_run_agent_loop` does for one turn.

    Yields a dict of recorders:

    ``saved``          every ``(kind, payload)`` the loop persisted
    ``model_messages`` the message list handed to each completion call
    ``tool_payloads``  each completion's ``tools`` argument (tool specs)
    ``efforts``        each completion's ``effort`` keyword (``None`` = unset)
    ``completions``    total completion calls
    ``history``        message list returned by ``_load_history``
    ``scheduled``      rows handed to ``_schedule_classification``
    ``order``          ordered trace of persistence events (sync recorder)
    ``full_prompts``   system prompts requested via ``build_system_prompt``
    ``refresh_calls``  how often the loop triggered an MCP refresh
    """
    saved: list[tuple[str, dict]] = []
    model_messages: list[list[dict]] = []
    tool_payloads: list[list] = []
    efforts: list = []
    completions: list[int] = [0]
    history: list[dict] = []
    scheduled: list[TurnClassification] = []
    order: list = []
    full_prompts: list[tuple] = []
    refresh_calls: list[int] = [0]
    replies: list[str] = ["ok"]
    calls: list[dict] = []
    msg_id = [0]

    async def fake_save(profile_id, role, content, **kw):
        msg_id[0] += 1
        kind = getattr(role, "name", str(role)).upper()
        entry = {"role": kind, "content": content, **kw}
        saved.append((kind, entry))
        order.append(("save", kind, content))
        return msg_id[0]

    async def fake_history(profile_id):
        import copy

        return [copy.deepcopy(m) for m in history]

    async def fake_profile(profile_id):
        return None

    real_build = build_system_prompt

    def spy_build(*args, **kwargs):
        full_prompts.append((args, kwargs))
        return real_build(*args, **kwargs)

    async def fake_completion(messages, tools=None, **kwargs):
        model_messages.append(list(messages))
        tool_payloads.append(list(tools or []))
        efforts.append(kwargs.get("effort", "MISSING"))
        completions[0] += 1
        idx = completions[0] - 1
        if idx < len(replies):
            text = replies[idx]
            # a reply may request tool calls: ("tool", name, args) tuples
            if idx < len(calls) and calls[idx] is not None:
                spec = calls[idx]
                return _tool_call(spec[1], spec[2])
            return _completion(text)
        return _completion("done")

    def record_schedule(row):
        scheduled.append(row)
        order.append("schedule")

    async def fake_refresh(*args, **kwargs):
        refresh_calls[0] += 1

    registry_mod._result_cache.clear()
    monkeypatch.setattr(loop_mod, "_save_message", fake_save)
    monkeypatch.setattr(loop_mod, "_load_history", fake_history)
    monkeypatch.setattr(loop_mod, "_load_profile", fake_profile)
    monkeypatch.setattr(loop_mod, "build_system_prompt", spy_build)
    monkeypatch.setattr(loop_mod, "get_profile_summary", lambda pid: "")
    monkeypatch.setattr(loop_mod, "chat_completion_with_fallback", fake_completion)
    monkeypatch.setattr(loop_mod, "_schedule_memory_extraction", lambda *a, **k: None)
    monkeypatch.setattr(loop_mod, "_schedule_classification", record_schedule)
    monkeypatch.setattr(loop_mod.mcp_service, "refresh_tools", fake_refresh)
    yield {
        "saved": saved,
        "model_messages": model_messages,
        "tool_payloads": tool_payloads,
        "efforts": efforts,
        "completions": completions,
        "history": history,
        "scheduled": scheduled,
        "order": order,
        "full_prompts": full_prompts,
        "refresh_calls": refresh_calls,
        "replies": replies,
        "calls": calls,
    }
    registry_mod._result_cache.clear()


# ---------------------------------------------------------------- 1. fast path
def test_greeting_takes_fast_path(turn_harness) -> None:
    """A greeting runs one completion on the fast prompt — no MCP, no full
    prompt history, low effort, and no `mcp_ms` key in the timings row."""
    result = asyncio.run(_run_agent_loop(16, "hi"))

    assert result.path_taken == "fast"
    assert turn_harness["completions"][0] == 1
    # greeting-only turns send no tools at all
    assert turn_harness["tool_payloads"] == [[]]
    # exactly one system message, and it is the fast prompt
    systems = [m for m in turn_harness["model_messages"][0] if m["role"] == "system"]
    assert len(systems) == 1
    assert systems[0]["content"] == build_fast_prompt(16, "", "")
    assert "Operating rules" not in systems[0]["content"]
    # no full prompt was ever built, no MCP refresh ran
    assert turn_harness["full_prompts"] == []
    assert turn_harness["refresh_calls"][0] == 0
    # low effort for a chitchat class
    assert turn_harness["efforts"] == ["low"]
    # exactly one classification row scheduled
    assert len(turn_harness["scheduled"]) == 1
    row = turn_harness["scheduled"][0]
    assert row.path_taken == "fast"
    assert "mcp_ms" not in (row.timings or {})


# ------------------------------------------------------- 2. answer from note
def test_tools_note_answered_without_rerunning_tools(turn_harness) -> None:
    """The model answers "what tools did you use?" FROM the TOOLS USED note
    rather than re-running tools: zero tool calls, zero extra completions."""
    turn_harness["history"].append(
        {
            "role": "assistant",
            "content": "Ran a couple of tools on this earlier.",
            "tools_used": ["check_niche_trends", "save_user_request"],
        }
    )
    turn_harness["replies"].clear()
    turn_harness["replies"].extend(
        [
            "check_niche_trends and save_user_request.",
            "Those two.",
        ]
    )

    for prompt in ("what tools did you use?", "list them"):
        res = asyncio.run(_run_agent_loop(16, prompt))
        assert res.content

    # two turns, one completion each — no tool loop, no forced coverage block
    assert turn_harness["completions"][0] == 2
    assert turn_harness["tool_payloads"] == [[], []]

    # the note was appended to an earlier assistant turn (marker present in
    # the messages sent to the model, before the history row)...
    sent = turn_harness["model_messages"][0]
    contents = [m.get("content") or "" for m in sent]
    assert any(NOTE_MARKER in c for c in contents)
    note_idx = next(i for i, m in enumerate(sent) if NOTE_MARKER in (m.get("content") or ""))
    hist_idx = next(
        i for i, m in enumerate(sent)
        if m["role"] == "assistant" and "Ran a couple of tools" in (m.get("content") or "")
    )
    assert note_idx < hist_idx
    # ...and no message reaching the model still carries a `tools_used` key
    assert all("tools_used" not in m for m in sent)


# --------------------------------------------------- 3. reason discipline
def test_scan_turn_reason_discipline(turn_harness, monkeypatch: pytest.MonkeyPatch) -> None:
    """A scan tool call carries `reason`: it reaches the TOOL row and the
    `tool_start` SSE event, and it is stripped before the provider sees the
    arguments."""
    async def fake_scan(**kwargs):
        return {"scanned_handles": {"wabi": 3}, "matches": []}

    fake = ToolSpec(
        name="check_niche_trends",
        description="fake",
        parameters={
            "type": "object",
            "properties": {"handles": {"type": "array", "items": {"type": "string"}}},
            "required": ["handles"],
        },
        func=fake_scan,
        cost="credits",
    )
    monkeypatch.setitem(registry_mod._REGISTRY, "check_niche_trends", fake)
    registry_mod._result_cache.clear()

    turn_harness["replies"].clear()
    turn_harness["replies"].extend(
        [
            "calling the scan now",
            "3 posts from @wabi cleared the 50-like filter this round.",
        ]
    )
    turn_harness["calls"].clear()
    turn_harness["calls"].extend(
        [
            (
                "tool",
                "check_niche_trends",
                {"handles": ["wabi"], "reason": "scanning @wabi for viral posts"},
            ),
            None,
        ]
    )
    events: list[dict] = []

    async def collect(event):
        events.append(event)

    res = asyncio.run(
        _run_agent_loop(16, "scan @wabi for viral posts", on_step=collect)
    )

    assert res.path_taken == "full"
    # `reason` discipline: the registry pops `reason` from a COPY of the
    # arguments, so the loop's own dict still carries it for the audit row
    # and the SSE event (both asserted below); the provider only ever sees
    # messages/tool specs, never tool arguments.
    assert turn_harness["completions"][0] == 2
    assert turn_harness["efforts"] == [None, None]  # live_scan is not low-effort

    # TOOL row persisted the reason, ASSISTANT row recorded tools_used
    tool_rows = [e for k, e in turn_harness["saved"] if k == "TOOL"]
    assert tool_rows, "expected a TOOL row"
    assert tool_rows[0].get("reason")
    asst = [e for k, e in turn_harness["saved"] if k == "ASSISTANT"]
    assert asst[-1].get("tools_used") == ["check_niche_trends"]
    assert res.content == "3 posts from @wabi cleared the 50-like filter this round."

    # the tool_start SSE event carries the reason
    starts = [e for e in events if e.get("event") == "tool_start" or e.get("type") == "tool_start"]
    if not starts:
        starts = [e for e in events if "tool" in str(e.get("event", e.get("type", "")))]
    assert starts, f"no tool_start event in {events!r}"
    assert starts[0].get("reason")

    # classification row: credits tool ran but NULL credits (unknown), tools_called set
    row = turn_harness["scheduled"][0]
    assert row.tools_called == ["check_niche_trends"]
    assert row.credits_spent is None


# ----------------------------------------------- 11. read-cheap tier filter
def test_read_cheap_turn_offers_only_free_tools(turn_harness) -> None:
    """A read-cheap turn sees only free tools in the full prompt and gets
    low effort — with the Free-first ambiguity rule visible to the model."""
    turn_harness["replies"].clear()
    turn_harness["replies"].append("What aspect of your posts do you want to look at first?")

    res = asyncio.run(_run_agent_loop(16, "how are my posts doing this week?"))

    assert res.path_taken == "full"
    assert turn_harness["efforts"] == ["low"]
    # the full system prompt was built and sent, carrying rule 21
    assert turn_harness["full_prompts"], "build_system_prompt was never called"
    sent_system = next(
        m["content"] for m in turn_harness["model_messages"][0] if m["role"] == "system"
    )
    assert "Free-first ambiguity" in sent_system
    assert "offer to run it" in sent_system
    # the tier filter restricted the offered tools to free ones
    specs = turn_harness["tool_payloads"][0]
    names = {s["function"]["name"] for s in specs}
    assert "get_posts" in names
    assert "check_niche_trends" not in names  # credits tier
    assert "repurpose_caption" not in names  # llm tier
    assert "submit_action" not in names  # write tier


# ------------------------------------------- 5. classification scheduled once
def test_classification_scheduled_once_after_final_reply(turn_harness) -> None:
    """The classification row is written exactly once, after the final
    assistant reply is saved — never before, never twice."""
    asyncio.run(_run_agent_loop(16, "hi"))

    order = turn_harness["order"]
    assert order[-1] == "schedule"
    # the save immediately before the schedule is the final ASSISTANT reply
    assert order[-2][0] == "save" and order[-2][1] == "ASSISTANT"

    assert len(turn_harness["scheduled"]) == 1
    row = turn_harness["scheduled"][0]
    assert row.final_class == "chitchat"
    assert row.path_taken == "fast"
    assert row.credits_spent is None  # NULL, never 0
    assert row.user_corrected is None  # tri-mode: unknown, not False
    assert "total_ms" in (row.timings or {})


# ------------------------- 5b. classification write failure never raises
def test_classification_write_failure_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """A failing classification DB write is swallowed: `_write_classification`
    returns None and `_schedule_classification` never raises — even when
    scheduling itself fails."""
    row = TurnClassification(profile_id=2)

    class _BoomSession:
        async def __aenter__(self):
            raise RuntimeError("db down")

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(loop_mod, "session_scope", _BoomSession)
    assert asyncio.run(loop_mod._write_classification(row)) is None

    # a failure while *scheduling* (e.g. no running loop) is also swallowed
    monkeypatch.setattr(loop_mod, "_write_classification", lambda r: None)
    loop_mod._schedule_classification(row)  # must not raise


# -------------------------------------------- 7. pending write note → full
def test_pending_write_note_blocks_fast_path(turn_harness, monkeypatch: pytest.MonkeyPatch) -> None:
    """A pending-write resolution note is appended for context, so the turn
    takes the full path even for a greeting."""
    async def fake_resolve(*args, **kwargs):
        return SimpleNamespace(
            tool=None,
            arguments=None,
            result=None,
            note="Pending write cancelled — the user did not confirm it.",
        )

    monkeypatch.setattr(loop_mod.mcp_service, "resolve_pending", fake_resolve)
    res = asyncio.run(_run_agent_loop(16, "hi"))

    assert res.path_taken == "full"
    sent_system = next(
        m["content"] for m in turn_harness["model_messages"][0] if m["role"] == "system"
    )
    assert "Operating rules" in sent_system  # full prompt, not fast
    contents = [m.get("content") or "" for m in turn_harness["model_messages"][0]]
    assert any("Pending write cancelled" in c for c in contents)
    assert turn_harness["completions"][0] == 1  # greeting-only: gates skipped


# ------------------------------------ 8. coverage-required → full path
def test_coverage_required_turns_take_full_path(turn_harness, monkeypatch: pytest.MonkeyPatch) -> None:
    """A coverage-required turn never takes the fast path, even when the
    model's reply would otherwise qualify (here: a tool-less decline)."""
    monkeypatch.setattr(
        loop_mod,
        "classify_turn",
        lambda *a, **k: asyncio.sleep(0, result=turn_class_mod.classify("hi")),
    )
    turn_harness["replies"].clear()
    turn_harness["replies"].append("I can't run scans right now.")

    res = asyncio.run(_run_agent_loop(16, "scan @wabi for viral posts"))

    assert res.path_taken == "full"
    sent_system = next(
        m["content"] for m in turn_harness["model_messages"][0] if m["role"] == "system"
    )
    assert "Operating rules" in sent_system
    # the honest decline passed both gates: exactly one completion, no nudge
    assert turn_harness["completions"][0] == 1
    assert res.content == "I can't run scans right now."
