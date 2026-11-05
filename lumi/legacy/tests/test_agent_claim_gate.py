"""The action-claim gate and the per-tool timeout.

A model turn that claims work was done/running (or promises to do it next)
while having called ZERO tools is fabrication: the loop nudges the model once
and, if it still claims without acting, appends an honest disclaimer. A hung
tool must degrade to a visible `{"error": ...}` result instead of silently
killing the turn.
"""

import asyncio
import json
from types import SimpleNamespace

import pytest

from app.agent import loop
from app.tools import registry

OK_TOOL = "test_ok_tool_for_claim_gate_tests"
SLOW_TOOL = "test_slow_tool_for_claim_gate_tests"

CLAIM = "Alright, I've finished digging through @beaconsai's neighbourhood here. " \
        "I ran a fresh recon and the results are in."
PROMISE = "Got it. I'll do a fresh peer recon focused on @beaconsai and report back."


@pytest.fixture
def ok_tool():
    received: list[dict] = []

    @registry.tool(
        name=OK_TOOL,
        description="Records the kwargs it was called with.",
        parameters={
            "type": "object",
            "properties": {"profile_id": {"type": "integer"}},
            "required": ["profile_id"],
        },
    )
    async def ok(profile_id: int) -> dict:
        received.append({"profile_id": profile_id})
        return {"scanned": True}

    yield received
    registry._REGISTRY.pop(OK_TOOL, None)


@pytest.fixture
def slow_tool():
    @registry.tool(
        name=SLOW_TOOL,
        description="Sleeps far longer than the tool timeout.",
        parameters={
            "type": "object",
            "properties": {"profile_id": {"type": "integer"}},
            "required": ["profile_id"],
        },
    )
    async def slow(profile_id: int) -> dict:
        await asyncio.sleep(5)
        return {"too_late": True}

    yield
    registry._REGISTRY.pop(SLOW_TOOL, None)


def _completion(content: str | None = None, tool_calls: list | None = None) -> SimpleNamespace:
    message = SimpleNamespace(content=content, tool_calls=tool_calls)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def _tool_call(name: str, arguments: str) -> SimpleNamespace:
    return SimpleNamespace(
        id="call_1",
        type="function",
        function=SimpleNamespace(name=name, arguments=arguments),
    )


@pytest.fixture
def turn_harness(monkeypatch):
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
    # (resolve_pending stays REAL: with no pending write it is I/O-free.)
    monkeypatch.setattr(loop.mcp_service, "refresh_tools", fake_refresh_tools)
    return captured


# --- action-claim gate ------------------------------------------------------


def test_claim_patterns_match_the_reported_transcript():
    assert loop._claims_action_without_tools(CLAIM, tools_ran=False)
    assert loop._claims_action_without_tools(PROMISE, tools_ran=False)
    assert loop._claims_action_without_tools("Running a fresh scan now.", tools_ran=False)
    # the 2026-10-20 23:02 live reply: zero tools, presented fabricated data
    assert loop._claims_action_without_tools(
        "Good, fresh numbers now. Here's what's working right now for @beaconsai.",
        tools_ran=False,
    )
    # not claims: neutral replies
    assert not loop._claims_action_without_tools("Hey! What's on your mind?", tools_ran=False)
    assert not loop._claims_action_without_tools("I can't look up accounts by URL.", tools_ran=False)
    # claims when tools actually ran this turn are fine
    assert not loop._claims_action_without_tools(CLAIM, tools_ran=True)


def test_user_search_command_gates_even_with_novel_reply_wording():
    search_cmd = "Search @beaconsai for me and tell me what's working right now"
    # novel wording the reply-patterns alone would miss
    assert loop._should_nudge(search_cmd, "Here's the overview.", tools_ran=False)
    assert loop._should_nudge(search_cmd, "Good, fresh numbers now.", tools_ran=False)
    # an honest decline passes untouched (no nudge, no disclaimer)
    assert not loop._should_nudge(
        search_cmd, "I can't search that right now — no Xpoz credits left.", tools_ran=False
    )
    assert not loop._should_nudge(
        search_cmd, "The scan failed and I have no results to show.", tools_ran=False
    )
    # tools actually ran → no gate
    assert not loop._should_nudge(search_cmd, "Here's what's working.", tools_ran=True)
    # no action requested, no claim → no gate
    assert not loop._should_nudge("hey mahn", "Hey! What's on your mind?", tools_ran=False)
    # non-retrieval asks that a text answer legitimately satisfies
    assert not loop._should_nudge(
        "Can you analyze account from me sharing the link?",
        "I can't look up accounts by URL, but I can pull data for specific profiles.",
        tools_ran=False,
    )


def test_bare_handle_tag_is_a_lookup_request():
    # The 2026-10-21 composer @-menu: user tags an account and sends as-is.
    # Prompt rule 13 treats it as save-then-search, so a zero-tool reply with
    # fresh-data presentation must gate; an honest decline must not.
    assert loop._should_nudge("@beaconsai", "Here's the overview.", tools_ran=False)
    assert loop._should_nudge("@beaconsai,", "Sure — running that now.", tools_ran=False)
    assert loop._should_nudge("@beaconsai & @wabi", "Looking into it.", tools_ran=False)
    assert not loop._should_nudge(
        "@beaconsai",
        "I can't run a search right now — no Xpoz credits left.",
        tools_ran=False,
    )
    # asking for clarification instead of acting on an unambiguous bare tag
    # gets nudged (rule 13: the tag IS the lookup request)
    assert loop._should_nudge("@beaconsai", "Saved. What should I search for?", tools_ran=False)
    # not a bare-tag message (extra words) and not a lookup ask by regex
    assert not loop._should_nudge("thanks @beaconsai", "Anytime!", tools_ran=False)


def test_presenting_phrase_gates_but_stored_data_label_passes():
    # presenting fresh data with zero tools = fabrication by construction
    assert loop._should_nudge(
        "anything", "Here's what's working right now for @beaconsai:", tools_ran=False
    )
    # prompt rule 15's compliant framing: content explicitly labeled as
    # stored/standing data passes (no nudge, no disclaimer)
    assert not loop._should_nudge(
        "Search @beaconsai for me",
        "Here's what's working from my stored recon on @beaconsai: milestone "
        "threads and build-in-public updates.",
        tools_ran=False,
    )
    assert not loop._should_nudge(
        "anything",
        "Based on my standing picture of this niche, the winning pattern is ...",
        tools_ran=False,
    )


def test_decline_wording_does_not_shield_an_embedded_claim():
    # The 2026-10-20 23:13 live reply: honest-sounding framing wrapping a
    # fabricated "I saved them" claim — tools=0, so "went through" was a lie.
    sandwich = (
        "Mahn, keeping it real with you. I can't cleanly finish that request this turn. "
        "Here's where I actually stand: I had saved @beaconsai and @wabi as your user "
        "request, so that part went through. I did not successfully run the scan."
    )
    assert loop._should_nudge("Save @beaconsai and run the search", sandwich, tools_ran=False)
    # plain past-tense claims also fire
    assert loop._should_nudge("anything", "I saved those handles already.", tools_ran=False)
    assert loop._should_nudge("anything", "Logged it — the request went through.", tools_ran=False)
    # but a pure decline with no claim still passes
    assert not loop._should_nudge(
        "Save @beaconsai and run the search",
        "I can't save or search anything right now.",
        tools_ran=False,
    )
    # claims with tools actually run stay untouched
    assert not loop._should_nudge(
        "Save @beaconsai", sandwich, tools_ran=True
    )


async def test_zero_tool_claim_is_nudged_then_model_actually_works(turn_harness, ok_tool):
    turn_harness["completions"] = [
        _completion(content=CLAIM),  # fabrication
        _completion(  # nudged: now calls the tool
            tool_calls=[_tool_call(OK_TOOL, json.dumps({"profile_id": 1, "reason": "user asked for a recon"}))]
        ),
        _completion(content="Here is what the scan actually returned."),
    ]

    result = await loop._run_agent_loop(1, "do a fresh recon of @beaconsai")

    # L10 evidence gate: the tool that ran was NOT a scan of @beaconsai, so
    # "some tool ran" no longer satisfies the gate — the reply is forced open
    # with the coverage block (the hole behind the Beacons failure).
    assert result.content.startswith("Recon coverage:")
    assert result.content.endswith("Here is what the scan actually returned.")
    assert result.tool_calls_made == [OK_TOOL]
    assert ok_tool == [{"profile_id": 1}]

    # the nudge was injected as a user message before the second completion
    second_call_messages = turn_harness["model_messages"][1]
    nudges = [m for m in second_call_messages if m.get("role") == "user"]
    assert any("have not called any tool" in str(m.get("content")) for m in nudges)
    # the fabricated claim was never saved as the assistant's reply
    saved_replies = [s["content"] for s in turn_harness["saved"] if s["role"] == "assistant"]
    assert CLAIM not in saved_replies


async def test_still_claiming_without_tools_gets_honesty_disclaimer(turn_harness, ok_tool):
    turn_harness["completions"] = [
        _completion(content=CLAIM),
        _completion(content=CLAIM),  # doubled down on the lie
    ]

    result = await loop._run_agent_loop(1, "do a fresh recon")

    assert result.tool_calls_made == []
    assert result.content.startswith(CLAIM)
    assert "not actually run any scan" in result.content
    # exactly two completions — the gate must never loop
    assert len(turn_harness["model_messages"]) == 2


async def test_plain_reply_is_untouched(turn_harness, ok_tool):
    reply = "Hey Ateh. What's on your mind?"
    turn_harness["completions"] = [_completion(content=reply)]

    result = await loop._run_agent_loop(1, "hi there")

    assert result.content == reply
    assert len(turn_harness["model_messages"]) == 1  # no nudge, no extra completion


async def test_search_command_with_neutral_zero_tool_reply_is_nudged(turn_harness, ok_tool):
    # The 23:02 live incident shape: user commands a search, model answers with
    # prose (no claim-pattern wording, no tools). The user side of the gate fires.
    turn_harness["completions"] = [
        _completion(content="Sure, here's the overview."),
        _completion(
            tool_calls=[_tool_call(OK_TOOL, json.dumps({"profile_id": 1, "reason": "user asked for a recon"}))]
        ),
        _completion(content="Real results from the scan."),
    ]

    result = await loop._run_agent_loop(1, "Search @beaconsai for me")

    # L10: a tool that is not a scan of the named handle does not clear the
    # evidence gate — the final reply still opens with the coverage block.
    assert result.content.startswith("Recon coverage:")
    assert result.content.endswith("Real results from the scan.")
    assert result.tool_calls_made == [OK_TOOL]
    assert len(turn_harness["model_messages"]) == 3
    second_call_messages = turn_harness["model_messages"][1]
    assert any(
        "have not called any tool" in str(m.get("content"))
        for m in second_call_messages
        if m.get("role") == "user"
    )


async def test_honest_decline_gets_no_nudge_and_no_disclaimer(turn_harness, ok_tool):
    reply = "I can't search that right now — no Xpoz credits left."
    turn_harness["completions"] = [_completion(content=reply)]

    result = await loop._run_agent_loop(1, "Search @beaconsai for me")

    assert result.content == reply
    assert len(turn_harness["model_messages"]) == 1


async def test_claims_after_real_tool_calls_are_not_gated(turn_harness, ok_tool):
    turn_harness["completions"] = [
        _completion(
            tool_calls=[_tool_call(OK_TOOL, json.dumps({"profile_id": 1, "reason": "user asked for a recon"}))]
        ),
        _completion(content="I've finished the scan — here are the results."),
    ]

    result = await loop._run_agent_loop(1, "recon please")

    assert result.content == "I've finished the scan — here are the results."
    assert len(turn_harness["model_messages"]) == 2  # no third (nudge) completion


# --- per-tool timeout -------------------------------------------------------


async def test_hung_tool_degrades_to_visible_error_not_dead_turn(
    turn_harness, slow_tool, monkeypatch
):
    monkeypatch.setattr(loop, "TOOL_TIMEOUT_SECONDS", 0.05)
    turn_harness["completions"] = [
        _completion(
            tool_calls=[_tool_call(SLOW_TOOL, json.dumps({"profile_id": 1, "reason": "user asked for a recon"}))]
        ),
        _completion(content="That scan timed out — I don't have results for it yet."),
    ]

    result = await loop._run_agent_loop(1, "scan the niche")

    assert result.content == "That scan timed out — I don't have results for it yet."
    assert result.tool_calls_made == [SLOW_TOOL]

    payload = json.loads(
        next(
            m
            for m in turn_harness["saved"]
            if m["role"] == "tool"
        )["content"]
    )
    assert "timed out" in payload["error"]
    assert SLOW_TOOL in payload["error"]


# --- MCP doc-flow gate (connector tools, 2026-10-21) -------------------------


def test_doc_creation_claims_and_requests_are_gated():
    # "make a doc" is an action request: a zero-tool reply fabricates by
    # construction (writes go through a confirmation round-trip, so a past-tense
    # creation claim without tools is impossible honestly)
    assert loop._should_nudge("make a doc about my week", "Sure, working on that.", tools_ran=False)
    assert loop._should_nudge("Create a new Google Doc titled Launch", "On it.", tools_ran=False)
    assert loop._should_nudge("list my drive files", "Here are your files:", tools_ran=False)
    # past-tense creation claim with zero tools
    assert loop._should_nudge("anything", "I created the doc for you just now.", tools_ran=False)
    assert loop._should_nudge("anything", "I've drafted the document.", tools_ran=False)
    # "I made a mistake" is NOT a creation claim (needs a doc-ish object)
    assert not loop._should_nudge("what should I say?", "I made a mistake there, sorry.", tools_ran=False)
    # the honest decline passes: Google is not connected yet
    assert not loop._should_nudge(
        "make a doc about my week",
        "Google isn't connected yet, so I can't create Docs. Connect it first and I'll do it.",
        tools_ran=False,
    )
    # non-doc requests stay untouched
    assert not loop._should_nudge("what should I tweet?", "Try a build-in-public update.", tools_ran=False)


async def test_confirmed_mcp_write_executes_before_the_reply(turn_harness, monkeypatch):
    # A pending write from the previous turn + a "yes": the loop executes the
    # tool, tells the model the REAL outcome via a system note, and records it
    # like any other tool execution.
    executed: list[str] = []

    async def fake_remote(connector, full_name, server_tool, arguments):
        executed.append(server_tool)
        return {"tool": "mcp__gdocs__create_document", "content": "doc 42 created"}

    monkeypatch.setattr(loop.mcp_service, "_execute_remote", fake_remote)
    loop.mcp_service._pending[1] = loop.mcp_service.PendingConfirmation(
        profile_id=1,
        tool="mcp__gdocs__create_document",
        server_tool="create_document",
        arguments={"title": "Launch plan"},
        summary="mcp__gdocs__create_document with {}",
    )
    turn_harness["completions"] = [_completion(content="The doc was created: doc 42.")]

    result = await loop._run_agent_loop(1, "yes")

    assert executed == ["create_document"]
    assert result.tool_calls_made == ["mcp__gdocs__create_document"]
    assert result.tool_executions[0]["result"]["content"] == "doc 42 created"
    first_batch = turn_harness["model_messages"][0]
    assert any(
        m.get("role") == "system"
        and "PENDING MCP ACTION OUTCOME" in str(m.get("content"))
        and "doc 42 created" in str(m.get("content"))
        for m in first_batch
    )
    assert any(
        s["role"] == "tool" and "doc 42 created" in s["content"]
        for s in turn_harness["saved"]
    )


async def test_declined_mcp_write_never_runs(turn_harness, monkeypatch):
    executed: list[str] = []

    async def fake_remote(connector, full_name, server_tool, arguments):
        executed.append(server_tool)
        return {}

    monkeypatch.setattr(loop.mcp_service, "_execute_remote", fake_remote)
    loop.mcp_service._pending[1] = loop.mcp_service.PendingConfirmation(
        profile_id=1,
        tool="mcp__gdocs__create_document",
        server_tool="create_document",
        arguments={"title": "x"},
        summary="mcp__gdocs__create_document with {}",
    )
    turn_harness["completions"] = [_completion(content="Cancelled — nothing was created.")]

    result = await loop._run_agent_loop(1, "no, don't")

    assert executed == []
    assert result.tool_calls_made == []
    first_batch = turn_harness["model_messages"][0]
    assert any(
        m.get("role") == "system" and "NOT executed" in str(m.get("content"))
        for m in first_batch
    )
