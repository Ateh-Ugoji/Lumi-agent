from __future__ import annotations

import asyncio

import pytest

from lumi_ai.agent.streaming import stream_turn
from lumi_ai.tests.agent.harness import call, make_rig, say, tool, use

pytestmark = pytest.mark.asyncio


async def test_events_arrive_in_order_and_end_with_done():
    rig = make_rig([use(call("ok")), say("All done here.")], [tool("ok")])
    events = [e async for e in stream_turn(rig.loop, 7, "show my analytics")]
    assert [e.type for e in events] == ["tool_start", "tool_done", "done"]
    done = events[-1]
    assert done.data["content"] == "All done here."
    assert done.data["tool_executions"][0]["name"] == "ok"
    assert events[0].encode().startswith('data: {"type": "tool_start"')


async def test_a_failing_turn_becomes_an_error_event():
    rig = make_rig([], [tool("ok")])  # the model call raises AssertionError
    events = [e async for e in stream_turn(rig.loop, 7, "show my analytics")]
    assert [e.type for e in events] == ["error"]
    assert events[0].data["error"]


async def test_unknown_profile_is_an_error_event_not_an_exception():
    rig = make_rig([say("x")])
    events = [e async for e in stream_turn(rig.loop, 99, "hello")]
    assert events[0].type == "error" and "not found" in events[0].data["error"]


async def test_closing_the_stream_cancels_the_running_turn():
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def slow(ctx):
        started.set()
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            cancelled.set()
            raise

    rig = make_rig([use(call("slow")), say("never")], [tool("slow", slow)])
    gen = stream_turn(rig.loop, 7, "show my analytics")
    first = await gen.__anext__()
    assert first.type == "tool_start"
    await asyncio.wait_for(started.wait(), 1)
    await gen.aclose()
    await asyncio.wait_for(cancelled.wait(), 1)
