from __future__ import annotations

import asyncio

import pytest

from lumi_ai.agent.streaming import error_payload, stream_turn
from lumi_ai.providers.errors import (
    AllProvidersFailed,
    NoProviderConfigured,
    RequestTooLarge,
)
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
    assert events[0].data == {
        "code": "agent_error",
        "error": "The reply could not be completed.",
    }


async def test_unknown_profile_is_an_error_event_not_an_exception():
    rig = make_rig([say("x")])
    events = [e async for e in stream_turn(rig.loop, 99, "hello")]
    assert events[0].type == "error" and events[0].data["code"] == "not_found"


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


async def test_an_error_event_never_carries_the_exception_text(caplog):
    secret = "sk-live-0123456789 http://internal.host/db?password=hunter2"
    rig = make_rig([], [tool("ok")])

    async def boom(*_a, **_k):
        raise RuntimeError(secret)

    rig.loop.run_turn = boom
    with caplog.at_level("ERROR"):
        events = [e async for e in stream_turn(rig.loop, 7, "hi")]
    assert secret not in events[0].encode()
    assert events[0].data["code"] == "agent_error"
    assert secret in caplog.text  # the detail is kept server-side


@pytest.mark.parametrize(
    ("exc", "code"),
    [
        (NoProviderConfigured("GROQ_API_KEY missing"), "llm_not_configured"),
        (AllProvidersFailed(()), "llm_unavailable"),
        (RequestTooLarge(()), "request_too_large"),
        (LookupError("profile 9 not found"), "not_found"),
    ],
)
async def test_provider_failures_get_their_own_stable_code(exc, code):
    assert error_payload(exc)["code"] == code
    assert str(exc) not in error_payload(exc)["error"] or str(exc) == ""
