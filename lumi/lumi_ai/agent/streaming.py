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
from lumi_ai.providers.errors import (
    AllProvidersFailed,
    NoProviderConfigured,
    RequestTooLarge,
)

logger = logging.getLogger(__name__)


def error_payload(exc: Exception) -> dict[str, str]:
    """A stable ``code`` and a generic message. The detail goes to the server log, never out.

    ``error`` keeps the key the client already reads; ``code`` is what it can branch on.
    """
    if isinstance(exc, LookupError):
        code, message = "not_found", "Profile not found."
    elif isinstance(exc, RequestTooLarge):
        code, message = (
            "request_too_large",
            "The message is too long for the available models.",
        )
    elif isinstance(exc, NoProviderConfigured):
        code, message = "llm_not_configured", "No language model is configured."
    elif isinstance(exc, AllProvidersFailed):
        code, message = (
            "llm_unavailable",
            "The language models are unavailable right now. Try again shortly.",
        )
    else:
        code, message = "agent_error", "The reply could not be completed."
    return {"code": code, "error": message}


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
            await queue.put(SSEEvent("error", error_payload(exc)))
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
