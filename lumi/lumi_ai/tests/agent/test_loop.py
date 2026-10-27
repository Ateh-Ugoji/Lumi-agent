"""Full turns against a scripted model and in-memory ports.

Ports the integration cases of the legacy claim-gate, tool-error, coverage-gate, context-budget and
prompt-5 acceptance tests. Nothing here touches a network or a real key.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from lumi_ai.agent.loop import FALLBACK_REPLY, ProfileNotFound
from lumi_ai.agent.result import SSEEvent
from lumi_ai.config import AIConfig
from lumi_ai.ports import (
    ChatMessageOut,
    McpPendingResolution,
    McpToolSpec,
)
from lumi_ai.tests.agent.harness import (
    Judge,
    Turns,
    call,
    make_rig,
    say,
    tool,
    use,
)
from lumi_ai.tests.fakes import NOW, FakeMcp

pytestmark = pytest.mark.asyncio

CLAIM = (
    "Alright, I've finished digging through @beaconsai's neighbourhood here. "
    "I ran a fresh recon and the results are in."
)
RECON = "do a fresh recon of @beaconsai"


def history_row(i: int, role: str, content: str, tools_used=None) -> ChatMessageOut:
    return ChatMessageOut(
        id=i,
        profile_id=7,
        role=role,  # type: ignore[arg-type]
        content=content,
        created_at=NOW,
        tools_used=tools_used,
    )


# --- the basic turn -------------------------------------------------------------


async def test_greeting_takes_the_fast_path_with_no_tools_and_low_effort():
    rig = make_rig([say("Hey Ana. What's on your mind?")], [tool("ok")])
    result = await rig.run("hi there")

    assert result.content == "Hey Ana. What's on your mind?"
    assert result.path_taken == "fast"
    assert rig.llm.tools_seen == [[]]
    assert rig.llm.efforts == ["low"]
    system = rig.llm.system_text(0)
    assert "Operating rules" not in system
    assert "AGENT MEMORY (rolling" not in system
    assert "today's date: Tuesday, 27 October 2026" in system
    assert [m.role for m in rig.saved()] == ["user", "assistant"]
    assert result.assistant_message_id == 2


async def test_two_tools_in_a_row_are_executed_saved_and_streamed():
    async def get_thing(ctx, query):
        return {"profile": ctx.profile_id, "q": query}

    thing = tool(
        "get_thing",
        get_thing,
        parameters={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    )
    rig = make_rig(
        [
            use(call("get_thing", {"query": "alpha"}, "c1")),
            use(call("get_thing", {"query": "beta"}, "c2")),
            say("Both lookups are back."),
        ],
        [thing],
    )
    result = await rig.run("show me my stats please")

    assert result.content == "Both lookups are back."
    assert result.tool_calls_made == ("get_thing", "get_thing")
    assert result.path_taken == "full"
    assert [e.arguments["query"] for e in result.tool_executions] == ["alpha", "beta"]
    assert all(e.ok for e in result.tool_executions)

    roles = [m.role for m in rig.saved()]
    assert roles == ["user", "assistant", "tool", "assistant", "tool", "assistant"]
    tool_rows = rig.saved("tool")
    assert tool_rows[0].tool_name == "get_thing"
    assert [r.tool_call_id for r in tool_rows] == ["c1", "c2"]  # ports 1.5
    assert tool_rows[0].reason == "the user asked for this in their message"
    assert json.loads(tool_rows[0].content) == {"profile": 7, "q": "alpha"}
    assert rig.saved("assistant")[0].tool_calls[0]["function"]["name"] == "get_thing"
    final = rig.saved("assistant")[-1]
    assert final.tools_used == ("get_thing", "get_thing")
    assert not rig.saved("assistant")[0].tools_used  # the mid-loop row stays bare

    # the second completion saw the first tool result
    assert json.loads(rig.llm.tool_messages(1)[0]["content"])["q"] == "alpha"
    kinds = [e.type for e in rig.events]
    assert kinds == ["tool_start", "tool_done", "tool_start", "tool_done"]
    assert rig.events[0].data["reason"] == "the user asked for this in their message"


async def test_profile_id_comes_from_the_turn_never_from_the_model():
    seen = []

    async def handler(ctx, **kwargs):
        seen.append((ctx.profile_id, kwargs))
        return {"ok": True}

    spec = tool(
        "mine",
        handler,
        parameters={
            "type": "object",
            "properties": {"profile_id": {"type": "integer"}},
        },
    )
    rig = make_rig(
        [use(call("mine", {"profile_id": 999})), say("Done, here is the detail.")],
        [spec],
    )
    await rig.run("show my analytics")
    assert seen == [(7, {})]


async def test_unknown_profile_raises_and_stores_nothing():
    rig = make_rig([say("never reached")])
    with pytest.raises(ProfileNotFound):
        await rig.run("hello", profile_id=8)
    assert rig.chat.rows == []
    assert rig.llm.seen == []


async def test_iteration_cap_ends_with_the_honest_fallback():
    script = [use(call("ok", {}, f"c{i}")) for i in range(6)]
    rig = make_rig(script, [tool("ok")])
    result = await rig.run("show my analytics")
    assert result.content == FALLBACK_REPLY
    assert len(result.tool_calls_made) == 6
    assert rig.saved("assistant")[-1].content == FALLBACK_REPLY


# --- claim gate (ported from test_agent_claim_gate) -------------------------------


async def test_zero_tool_claim_is_nudged_then_model_actually_works():
    rig = make_rig(
        [say(CLAIM), use(call("ok")), say("Here is what the scan actually returned.")],
        [tool("ok")],
    )
    result = await rig.run(RECON)

    # the tool that ran was not a scan of @beaconsai, so the coverage gate still opens the reply
    assert result.content.startswith("Recon coverage:")
    assert result.content.endswith("Here is what the scan actually returned.")
    assert result.tool_calls_made == ("ok",)
    nudges = [m for m in rig.llm.seen[1] if m["role"] == "user"]
    assert any("have not called any tool" in m["content"] for m in nudges)
    assert CLAIM not in [m.content for m in rig.saved("assistant")]


async def test_still_claiming_without_tools_gets_the_honesty_disclaimer():
    rig = make_rig([say(CLAIM), say(CLAIM)], [tool("ok")])
    result = await rig.run("do a fresh recon")
    assert result.tool_calls_made == ()
    assert result.content.startswith(CLAIM)
    assert "not actually run any scan" in result.content
    assert len(rig.llm.seen) == 2  # the gate never loops


async def test_plain_reply_is_untouched_and_costs_one_completion():
    rig = make_rig([say("Sure, a short post works best on LinkedIn.")], [tool("ok")])
    result = await rig.run("what length works best for posts")
    assert result.content == "Sure, a short post works best on LinkedIn."
    assert len(rig.llm.seen) == 1


async def test_search_command_with_a_neutral_zero_tool_reply_is_nudged():
    rig = make_rig(
        [say("Sure, here's the overview."), use(call("ok")), say("Real results.")],
        [tool("ok")],
    )
    result = await rig.run("Search @beaconsai for me")
    assert result.content.endswith("Real results.")
    assert len(rig.llm.seen) == 3
    assert any(
        "have not called any tool" in m["content"]
        for m in rig.llm.seen[1]
        if m["role"] == "user"
    )


async def test_honest_decline_gets_no_nudge_and_no_disclaimer():
    reply = "I can't search that right now, no credits left."
    rig = make_rig([say(reply)], [tool("ok")])
    result = await rig.run("Search @beaconsai for me")
    assert result.content == reply
    assert len(rig.llm.seen) == 1


async def test_claims_after_real_tool_calls_are_not_gated():
    rig = make_rig(
        [use(call("ok")), say("I've finished the scan, here are the results.")],
        [tool("ok")],
    )
    result = await rig.run("recon please")
    assert result.content == "I've finished the scan, here are the results."
    assert len(rig.llm.seen) == 2


# --- tool failures (ported from test_agent_tool_errors) ---------------------------


async def test_raising_tool_is_handed_to_the_model_as_an_error():
    async def boom(ctx):
        raise RuntimeError("provider exploded")

    rig = make_rig(
        [use(call("boom")), say("That lookup failed, so I cannot give numbers.")],
        [tool("boom", boom)],
    )
    result = await rig.run("show my analytics")
    err = json.loads(rig.llm.tool_messages(1)[0]["content"])["error"]
    assert "provider exploded" in err and "Do not pretend it worked" in err
    assert result.tool_executions[0].ok is False
    assert result.content.startswith("That lookup failed")


async def test_malformed_arguments_do_not_abort_the_turn():
    rig = make_rig(
        [use(call("ok", "{not json")), say("I could not run that call.")], [tool("ok")]
    )
    result = await rig.run("show my analytics")
    err = json.loads(rig.llm.tool_messages(1)[0]["content"])["error"]
    assert "not valid JSON" in err
    assert result.tool_executions[0].ok is False


async def test_missing_required_argument_is_reported_to_the_model():
    spec = tool(
        "needs_q",
        parameters={
            "type": "object",
            "properties": {"q": {"type": "string"}},
            "required": ["q"],
        },
    )
    rig = make_rig([use(call("needs_q", {})), say("I need a query first.")], [spec])
    await rig.run("show my analytics")
    err = json.loads(rig.llm.tool_messages(1)[0]["content"])["error"]
    assert "needs_q rejected the call" in err and "q" in err


async def test_missing_reason_is_reported_to_the_model():
    rig = make_rig(
        [use(call("ok", {"reason": ""})), say("Let me retry with a reason.")],
        [tool("ok")],
    )
    await rig.run("show my analytics")
    err = json.loads(rig.llm.tool_messages(1)[0]["content"])["error"]
    assert "reason" in err


async def test_extra_argument_is_dropped_and_the_turn_survives():
    got = []

    async def handler(ctx, **kwargs):
        got.append(kwargs)
        return {"ok": 1}

    spec = tool(
        "t",
        handler,
        parameters={"type": "object", "properties": {"a": {"type": "string"}}},
    )
    rig = make_rig(
        [use(call("t", {"a": "x", "zzz": 1})), say("All good here.")], [spec]
    )
    await rig.run("show my analytics")
    assert got == [{"a": "x"}]


async def test_hung_tool_degrades_to_a_visible_error_not_a_dead_turn():
    async def hang(ctx):
        await asyncio.sleep(5)

    rig = make_rig(
        [use(call("hang")), say("That service is not answering.")],
        [tool("hang", hang)],
        config=AIConfig(tool_timeout_seconds=0.05),
    )
    result = await rig.run("show my analytics")
    err = json.loads(rig.llm.tool_messages(1)[0]["content"])["error"]
    assert "timed out" in err
    assert result.content == "That service is not answering."


async def test_a_write_tool_gets_a_cancel_token_that_a_timeout_cancels():
    from lumi_ai import cancel

    seen: list = []

    async def slow_write(ctx):
        seen.append(cancel.current.get())
        await asyncio.sleep(5)

    rig = make_rig(
        [use(call("save")), say("It may not have been saved.")],
        [tool("save", slow_write, cost="write")],
        config=AIConfig(tool_timeout_seconds=0.05),
    )
    await rig.run("save it")
    assert len(seen) == 1 and seen[0].cancelled
    assert cancel.current.get() is None  # the turn does not leak its token
    assert "timed out" in json.loads(rig.llm.tool_messages(1)[0]["content"])["error"]


async def test_a_read_tool_runs_without_a_cancel_token():
    from lumi_ai import cancel

    seen: list = []

    async def read(ctx):
        seen.append(cancel.current.get())
        return {"ok": True}

    rig = make_rig([use(call("peek")), say("Done.")], [tool("peek", read)])
    await rig.run("look")
    assert seen == [None]


async def test_a_write_that_committed_before_the_timeout_is_reported_as_partial():
    from lumi_ai import cancel

    async def partial(ctx):
        with cancel.current.get().commit_gate():
            pass  # one commit went through
        await asyncio.sleep(5)

    rig = make_rig(
        [use(call("save")), say("Possibly partial.")],
        [tool("save", partial, cost="write")],
        config=AIConfig(tool_timeout_seconds=0.05),
    )
    await rig.run("save it")
    err = json.loads(rig.llm.tool_messages(1)[0]["content"])["error"]
    assert "already been saved" in err and "1 of its" in err


class _SlowMcp(FakeMcp):
    """A connector whose call parks a write, then hangs past the tool timeout."""

    def __init__(self, specs):
        super().__init__(specs)
        self.tokens: list = []

    async def call(self, profile_id, name, args):
        from lumi_ai import cancel

        self.tokens.append(cancel.current.get())
        await asyncio.sleep(5)


@pytest.mark.parametrize(
    ("spec_kwargs", "gets_token"),
    [
        ({"cost": "write", "requires_confirmation": True}, True),
        ({"cost": "free", "requires_confirmation": True}, True),
        ({"cost": "free"}, False),
    ],
)
async def test_an_mcp_write_tool_gets_a_cancel_token_that_a_timeout_cancels(
    spec_kwargs, gets_token
):
    from lumi_ai.ports import McpToolSpec

    spec = McpToolSpec(
        "mcp__gdocs__create_doc",
        "Create a document.",
        {"type": "object", "properties": {}},
        **spec_kwargs,
    )
    mcp = _SlowMcp([spec])
    rig = make_rig(
        [use(call("mcp__gdocs__create_doc")), say("It did not finish.")],
        [tool("ok")],
        mcp=mcp,
        config=AIConfig(tool_timeout_seconds=0.05),
    )
    await rig.run("create the doc")
    assert len(mcp.tokens) == 1
    if gets_token:
        assert mcp.tokens[0] is not None and mcp.tokens[0].cancelled
    else:
        assert mcp.tokens[0] is None


# --- coverage gate (ported from test_coverage_gate) -------------------------------


def scan_tool(result: dict):
    async def scan(ctx, **kwargs):
        return result

    return tool(
        "check_niche_trends",
        scan,
        cost="credits",
        parameters={"type": "object", "properties": {"handles": {"type": "array"}}},
    )


async def test_failed_scan_opens_the_reply_with_a_coverage_block():
    scan = scan_tool(
        {
            "scanned_handles": {"beaconsai": 10},
            "failed_handles": ["@wabi: provider 402"],
            "viral_posts": [
                {
                    "author": "wabi",
                    "caption": "x",
                    "likes": 77,
                    "avatar_url": "https://cdn.example/wabi.jpg",
                },
                {"author": "other", "caption": "y", "likes": 5},
            ],
        }
    )
    rig = make_rig(
        [
            use(call("check_niche_trends", {"handles": ["beaconsai", "wabi"]})),
            say("Here is the full picture of both accounts."),
        ],
        [scan],
    )
    result = await rig.run("study @beaconsai and @wabi and write me a plan")
    assert result.content.startswith("Recon coverage:")
    assert "@beaconsai: scanned" in result.content and "@wabi: failed" in result.content
    assert "full picture" not in result.content
    assert "partial picture" in result.content
    samples = result.tool_executions[0].sample_posts
    assert samples[0]["author"] == "wabi"
    assert samples[0]["avatar_url"] == "https://cdn.example/wabi.jpg"
    assert samples[1]["avatar_url"] == ""  # unknown stays an empty string


async def test_complete_coverage_leaves_the_reply_untouched():
    scan = scan_tool({"scanned_handles": {"beaconsai": 12}, "failed_handles": []})
    rig = make_rig(
        [
            use(call("check_niche_trends", {"handles": ["beaconsai"]})),
            say("Their posts lean on short hooks."),
        ],
        [scan],
    )
    result = await rig.run("scan @beaconsai for me")
    assert result.content == "Their posts lean on short hooks."


async def test_gate_fires_even_when_an_unrelated_tool_ran():
    rig = make_rig(
        [
            use(call("ok")),
            say("Here is your plan."),
            say("Still a plan with no scan."),
        ],
        [tool("ok")],
    )
    result = await rig.run("study @beaconsai and write me a plan")
    assert any(
        "@beaconsai" in m["content"] for m in rig.llm.seen[2] if m["role"] == "user"
    )
    assert result.content.startswith("Recon coverage:")


async def test_a_named_handle_forces_the_full_path_even_for_chitchat_class():
    rig = make_rig([say("Hey! Sure.")], [tool("ok")])
    result = await rig.run("hey @beaconsai")
    assert result.path_taken in {"fast", "full"}
    # a bare tagged handle is a lookup request, so the operating rules must be loaded
    assert "Operating rules" in rig.llm.system_text(0)


async def test_length_finish_reason_continues_once():
    rig = make_rig(
        [say("First part of the plan and then ", "length"), say("the rest of it.")],
        [tool("ok")],
    )
    result = await rig.run("write me a long plan for next week")
    assert result.content == "First part of the plan and then the rest of it."


async def test_repeated_length_says_where_it_was_cut():
    rig = make_rig(
        [say("Part one ", "length"), say("part two ", "length")], [tool("ok")]
    )
    result = await rig.run("write me a long plan for next week")
    assert result.content.startswith("Part one part two")
    assert "cut off again" in result.content


# --- context, history and notes ---------------------------------------------------


async def test_tools_note_and_history_reach_the_model_without_the_key():
    history = [
        history_row(1, "user", "check my stats"),
        history_row(2, "assistant", "Here they are.", ("get_analytics", "get_posts")),
        history_row(3, "tool", "{}"),
        history_row(4, "user", "which tools did you use?"),
    ]
    rig = make_rig(
        [say("I used get_analytics and get_posts.")], [tool("ok")], history=history
    )
    await rig.run("which tools did you use?")
    seen = rig.llm.seen[0]
    assert any(
        m["role"] == "system"
        and "TOOLS USED" in m["content"]
        and "get_analytics" in m["content"]
        for m in seen
    )
    assert all("tools_used" not in m for m in seen)
    assert [m["role"] for m in seen if m["role"] != "system"] == [
        "user",
        "assistant",
        "user",
    ]  # the tool row never rides the history
    assert rig.llm.tools_seen[0] == []  # history_meta offers no tools


async def test_oversized_history_is_trimmed_to_the_budget():
    long = "x" * 4000
    history = [
        history_row(i, "user" if i % 2 else "assistant", long) for i in range(1, 9)
    ]
    history.append(history_row(9, "user", "what should I post tomorrow"))
    rig = make_rig(
        [say("Post a short note about your launch.")],
        [],
        history=history,
        config=AIConfig(max_request_tokens=2500),
    )
    await rig.run("what should I post tomorrow")
    sent = rig.llm.seen[0]
    assert sent[-1]["content"] == "what should I post tomorrow"
    assert sent[0]["role"] == "system"
    assert len(sent) < len(history) + 1


async def test_memory_summary_voice_of_profile_and_niche_ride_the_system_prompt():
    rig = make_rig([say("Short answer.")], [tool("ok")])
    await rig.run("what should I post tomorrow")
    system = rig.llm.system_text(0)
    assert "Prefers short posts." in system
    assert "- niche: AI founders" in system
    assert "- connected platforms: linkedin" in system


# --- pending MCP writes (ported from test_agent_claim_gate) -----------------------


async def test_confirmed_mcp_write_executes_before_the_reply():
    mcp = FakeMcp()
    mcp.pending = McpPendingResolution(
        note="SYSTEM NOTE: the doc was created, id d1.",
        tool="mcp__gdocs__create_doc",
        arguments={"title": "Plan"},
        result={"status": "ok", "id": "d1"},
    )
    rig = make_rig([say("Done, your doc is created.")], [tool("ok")], mcp=mcp)
    result = await rig.run("yes, go ahead")
    assert result.tool_calls_made == ("mcp__gdocs__create_doc",)
    assert result.path_taken == "full"
    assert "SYSTEM NOTE: the doc was created" in rig.llm.system_text(0)
    row = rig.saved("tool")[0]
    assert row.reason == "user confirmed the pending write"
    assert [e.type for e in rig.events] == ["tool_start", "tool_done"]
    assert rig.saved("assistant")[-1].tools_used == ("mcp__gdocs__create_doc",)


async def test_declined_mcp_write_never_runs_but_the_note_reaches_the_model():
    mcp = FakeMcp()
    mcp.pending = McpPendingResolution(note="SYSTEM NOTE: cancelled, nothing ran.")
    rig = make_rig([say("Okay, I cancelled it.")], [tool("ok")], mcp=mcp)
    result = await rig.run("no thanks")
    assert result.tool_calls_made == ()
    assert result.path_taken == "full"
    assert "cancelled, nothing ran" in rig.llm.system_text(0)
    assert mcp.calls == []


async def test_connector_tools_are_offered_when_connected_and_absent_when_down():
    spec = McpToolSpec(
        name="mcp__gdrive__list_files",
        description="list files",
        parameters={"type": "object", "properties": {}},
        cost="free",
    )
    mcp = FakeMcp([spec])
    rig = make_rig([say("Here are your files.")], [tool("ok")], mcp=mcp)
    await rig.run("what can you do with my connectors")
    names = [t["function"]["name"] for t in rig.llm.tools_seen[0]]
    assert "mcp__gdrive__list_files" in names

    down = FakeMcp([spec])
    down.fail_list = True
    rig = make_rig([say("Google is not connected.")], [tool("ok")], mcp=down)
    await rig.run("what can you do with my connectors")
    names = [t["function"]["name"] for t in rig.llm.tools_seen[0]]
    assert "mcp__gdrive__list_files" not in names and "ok" in names


# --- tiers ------------------------------------------------------------------------


async def test_read_cheap_turn_offers_only_free_tools():
    paid = tool("paid", cost="credits")
    rig = make_rig([say("Your top post got 40 likes.")], [tool("free_one"), paid])
    await rig.run("how are my posts doing?")
    names = [t["function"]["name"] for t in rig.llm.tools_seen[0]]
    assert "free_one" in names and "paid" not in names
    assert rig.llm.efforts[0] == "low"


# --- the judge: early exit and memory gate ----------------------------------------


async def test_judge_early_exit_forces_the_final_answer_without_tools():
    judge = Judge(lambda q: {"sufficient": 0.9})
    rig = make_rig(
        [
            use(call("ok", {}, "c1")),
            use(call("ok", {}, "c2")),
            say("Enough, here it is."),
        ],
        [tool("ok")],
        judge=judge,
    )
    result = await rig.run("show my analytics")
    assert result.content == "Enough, here it is."
    assert rig.llm.tools_seen[2] == []  # the third completion had no tools
    assert rig.llm.tools_seen[1] != []


async def test_no_judge_verdict_keeps_the_loop_going():
    rig = make_rig(
        [
            use(call("ok", {}, "c1")),
            use(call("ok", {}, "c2")),
            use(call("ok", {}, "c3")),
            say("x done."),
        ],
        [tool("ok")],
        judge=Judge(None),
    )
    await rig.run("show my analytics")
    assert rig.llm.tools_seen[2] != []


async def test_memory_extraction_is_gated_by_the_judge_and_fails_open():
    gate = Judge(lambda q: {"durable": 0.1} if "durable" in q else None)
    rig = make_rig([say("Noted, anything else?")], [tool("ok")], judge=gate)
    await rig.run("what should I post tomorrow")
    assert rig.extractor.calls == []

    keep = Judge(lambda q: {"durable": 0.9} if "durable" in q else None)
    rig = make_rig([say("Noted, anything else?")], [tool("ok")], judge=keep)
    await rig.run("I always post at 8am, remember it")
    assert rig.extractor.calls[0][0] == 7

    rig = make_rig([say("Noted, anything else?")], [tool("ok")], judge=Judge(None))
    await rig.run("I always post at 8am")
    assert len(rig.extractor.calls) == 1  # no verdict, extract anyway


# --- turn log ---------------------------------------------------------------------


async def test_turn_record_is_written_once_with_honest_timings():
    judge = Judge(None)
    rig = make_rig(
        [use(call("ok")), say("Here you go, all set.")], [tool("ok")], judge=judge
    )
    result = await rig.run("show my analytics")
    assert len(rig.turns.records) == 1
    rec = rig.turns.records[0]
    assert rec.profile_id == 7 and rec.message_id == 1
    assert rec.path_taken == result.path_taken
    assert rec.tools_called == ("ok",)
    assert rec.timings["model"] == "fake-model"
    assert rec.timings["prompt_tokens"] == 200
    assert "mcp_ms" not in rec.timings  # not measured: absent, never 0
    assert "judge_ms" not in rec.timings or rec.timings["judge_ms"] > 0


async def test_a_failing_turn_log_never_breaks_the_turn():
    rig = make_rig([say("Fine, no problem.")], [tool("ok")], turns=Turns(fail=True))
    result = await rig.run("what should I post tomorrow")
    assert result.content == "Fine, no problem."


# --- result shape -----------------------------------------------------------------


async def test_analytics_result_ships_in_the_execution_for_the_chart():
    async def get_analytics(ctx):
        return {"total_impressions": 120, "reach_series": [1, 2]}

    rig = make_rig(
        [use(call("get_analytics")), say("You had 120 impressions.")],
        [tool("get_analytics", get_analytics)],
    )
    result = await rig.run("how are my impressions")
    shipped = result.tool_executions[0].as_dict()
    assert shipped["name"] == "get_analytics"
    assert shipped["result"]["total_impressions"] == 120


async def test_connect_account_ships_only_its_allowlisted_fields():
    async def connect_account(ctx, platform="x"):
        return {
            "already_connected": False,
            "platform": "x",
            "connect_url": "https://example.test/oauth/start?state=abc",
            "handle": "ana",
            "debug": "internal detail",
            "nested": {"token": "secret"},
        }

    rig = make_rig(
        [use(call("connect_account")), say("Here is your link.")],
        [tool("connect_account", connect_account)],
    )
    shipped = (await rig.run("connect my x account")).tool_executions[0].as_dict()
    assert shipped["result"] == {
        "already_connected": False,
        "platform": "x",
        "connect_url": "https://example.test/oauth/start?state=abc",
        "handle": "ana",
    }


async def test_connect_account_error_text_never_reaches_the_frontend():
    async def connect_account(ctx, platform="x"):
        return {
            "error": "ConnectionError: postgres://user:pw@db/internal",
            "platform": "x",
        }

    rig = make_rig(
        [use(call("connect_account")), say("It failed.")],
        [tool("connect_account", connect_account)],
    )
    execution = (await rig.run("connect my x account")).tool_executions[0]
    assert execution.ok is False and "result" not in execution.as_dict()


async def test_other_tools_ship_no_result_at_all():
    async def get_posts(ctx):
        return {"posts": [{"id": 1}], "secret": "internal"}

    rig = make_rig(
        [use(call("get_posts")), say("Done.")], [tool("get_posts", get_posts)]
    )
    shipped = (await rig.run("show posts")).tool_executions[0].as_dict()
    assert "result" not in shipped


async def test_a_confirmed_mcp_write_result_is_not_shipped():
    mcp = FakeMcp()
    mcp.pending = McpPendingResolution(
        note="SYSTEM NOTE: done.",
        tool="mcp__gdocs__create_doc",
        arguments={"title": "Plan"},
        result={"status": "ok", "id": "d1", "token": "t"},
    )
    rig = make_rig([say("Done.")], [tool("ok")], mcp=mcp)
    result = await rig.run("yes, go ahead")
    assert "result" not in result.tool_executions[0].as_dict()


async def test_a_broken_event_listener_never_kills_the_turn():
    rig = make_rig([use(call("ok")), say("Still works fine.")], [tool("ok")])

    async def bad(event: SSEEvent):
        raise RuntimeError("client gone")

    result = await rig.loop.run_turn(7, "show my analytics", bad)
    assert result.content == "Still works fine."
