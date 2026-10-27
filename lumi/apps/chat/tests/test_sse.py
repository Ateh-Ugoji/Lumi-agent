"""``apps.chat.sse``: encoding, pings, cancellation on client disconnect, task tracking."""

import asyncio

import pytest

from apps.chat import sse
from lumi_ai.agent.result import SSEEvent


async def collect(gen):
    return [chunk async for chunk in gen]


async def two_events():
    yield SSEEvent(
        "tool_start", {"tool": "get_analytics", "arguments": {}, "reason": "why"}
    )
    yield SSEEvent("tool_done", {"tool": "get_analytics", "sample_posts": []})
    yield SSEEvent("done", {"content": "hola ñ", "tool_executions": []})


async def test_events_are_encoded_as_data_lines():
    chunks = await collect(sse.stream(two_events()))
    assert [c.split('"type": "')[1].split('"')[0] for c in chunks] == [
        "tool_start",
        "tool_done",
        "done",
    ]
    assert all(c.startswith("data: ") and c.endswith("\n\n") for c in chunks)
    assert "hola ñ" in chunks[-1]  # not escaped to \u00f1
    assert not sse.ACTIVE


async def test_nothing_is_sent_after_done():
    async def noisy():
        yield SSEEvent("done", {"content": "x", "tool_executions": []})
        yield SSEEvent("tool_start", {"tool": "late"})

    chunks = await collect(sse.stream(noisy()))
    assert len(chunks) == 1


async def test_a_quiet_turn_gets_pings():
    release = asyncio.Event()

    async def slow():
        await release.wait()
        yield SSEEvent("done", {"content": "ok", "tool_executions": []})

    gen = sse.stream(slow(), ping_seconds=0.01)
    assert await gen.__anext__() == ": ping\n\n"
    assert await gen.__anext__() == ": ping\n\n"
    release.set()
    assert "done" in await gen.__anext__()
    assert await collect(gen) == []


async def test_closing_the_stream_cancels_the_turn():
    started, cancelled = asyncio.Event(), asyncio.Event()

    async def turn():
        yield SSEEvent("tool_start", {"tool": "t", "arguments": {}, "reason": None})
        started.set()
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            cancelled.set()
            raise
        yield SSEEvent("done", {"content": "never", "tool_executions": []})

    gen = sse.stream(turn())
    await gen.__anext__()
    await asyncio.wait_for(started.wait(), 1)
    assert len(sse.ACTIVE) == 1
    await gen.aclose()  # what the server does when the client disconnects
    assert cancelled.is_set()
    assert not sse.ACTIVE


async def test_cancelling_the_response_task_cancels_the_turn():
    cancelled = asyncio.Event()

    async def turn():
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            cancelled.set()
            raise
        yield SSEEvent("done", {})

    task = asyncio.ensure_future(collect(sse.stream(turn())))
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert cancelled.is_set()
    assert not sse.ACTIVE


async def test_a_crash_becomes_a_short_error_event_without_the_message():
    async def boom():
        yield SSEEvent("tool_start", {"tool": "t"})
        raise RuntimeError("secret sk-123 at /srv/app/x.py line 9")

    chunks = await collect(sse.stream(boom()))
    assert '"type": "error"' in chunks[-1]
    assert "sk-123" not in "".join(chunks)
    assert "/srv/app" not in "".join(chunks)
    assert not sse.ACTIVE


async def test_cancel_all_stops_every_live_stream():
    async def forever():
        await asyncio.sleep(60)
        yield SSEEvent("done", {})

    gens = [sse.stream(forever()) for _ in range(3)]
    waiting = [asyncio.ensure_future(g.__anext__()) for g in gens]
    await asyncio.sleep(0.05)
    assert len(sse.ACTIVE) == 3
    await sse.cancel_all()
    assert not sse.ACTIVE
    for w in waiting:
        w.cancel()
    await asyncio.gather(*waiting, return_exceptions=True)
