"""Server-sent events for ``POST /chat/stream``.

One *pump* task per stream reads the runtime's events into a queue. The response generator waits
on that queue with a timeout so it can send ``: ping`` when the turn is quiet. When the client
goes away the generator is closed (or cancelled by ASGI) and its ``finally`` cancels the pump,
which closes the runtime's iterator and with it the turn. Every pump is held in ``ACTIVE`` until
it has finished, so nothing is garbage collected mid-turn and shutdown can cancel the lot.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator

from lumi_ai.agent.result import SSEEvent

logger = logging.getLogger(__name__)

PING_SECONDS = 15.0
PING = ": ping\n\n"
GENERIC_ERROR = "No se pudo completar la respuesta."

#: Pump tasks that have not finished yet.
ACTIVE: set[asyncio.Task[None]] = set()


def error_event(message: str = GENERIC_ERROR) -> SSEEvent:
    return SSEEvent("error", {"error": message})


async def _pump(
    events: AsyncIterator[SSEEvent], queue: asyncio.Queue[SSEEvent | None]
) -> None:
    try:
        async for event in events:
            await queue.put(event)
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("chat stream failed")
        await queue.put(error_event())
    finally:
        aclose = getattr(events, "aclose", None)
        if aclose is not None:
            with contextlib.suppress(Exception):
                await aclose()
        queue.put_nowait(None)


async def stream(
    events: AsyncIterator[SSEEvent], *, ping_seconds: float | None = None
) -> AsyncIterator[str]:
    """Encode ``events`` as SSE text, with pings, ending after ``done`` or ``error``."""
    interval = PING_SECONDS if ping_seconds is None else ping_seconds
    queue: asyncio.Queue[SSEEvent | None] = asyncio.Queue()
    pump = asyncio.ensure_future(_pump(events, queue))
    ACTIVE.add(pump)
    pump.add_done_callback(ACTIVE.discard)
    try:
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=interval)
            except TimeoutError:
                yield PING
                continue
            if event is None:
                return
            yield event.encode()
            if event.type in ("done", "error"):
                return
    finally:
        if not pump.done():
            pump.cancel()
        await asyncio.gather(pump, return_exceptions=True)
        ACTIVE.discard(pump)


async def cancel_all() -> None:
    """Cancel every live stream and wait for them. For shutdown and tests."""
    tasks = list(ACTIVE)
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
