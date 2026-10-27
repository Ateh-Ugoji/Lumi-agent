"""Server-sent events for one turn, with clean cancellation.

``stream_turn`` runs the turn in its own task and yields events as they happen. If the consumer
goes away (client disconnect, generator closed) the turn is cancelled instead of running to the
end for a reader that no longer exists.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator

from lumi_ai.agent.loop import AgentLoop
from lumi_ai.agent.result import SSEEvent

logger = logging.getLogger(__name__)


async def stream_turn(
    loop: AgentLoop, profile_id: int, message: str
) -> AsyncIterator[SSEEvent]:
    queue: asyncio.Queue[SSEEvent | None] = asyncio.Queue()

    async def on_event(event: SSEEvent) -> None:
        await queue.put(event)

    async def runner() -> None:
        try:
            result = await loop.run_turn(profile_id, message, on_event)
            await queue.put(
                SSEEvent(
                    "done",
                    {
                        "content": result.content,
                        "tool_executions": [
                            e.as_dict() for e in result.tool_executions
                        ],
                    },
                )
            )
        except Exception as exc:
            logger.exception("agent stream failed (profile %s)", profile_id)
            await queue.put(
                SSEEvent("error", {"error": str(exc) or type(exc).__name__})
            )
        finally:
            await queue.put(None)

    task = asyncio.create_task(runner())
    try:
        while (event := await queue.get()) is not None:
            yield event
    finally:
        if not task.done():
            task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task
