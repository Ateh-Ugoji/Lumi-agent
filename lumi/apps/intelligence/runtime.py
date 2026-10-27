"""The chat runtime ``apps.core.agent_runtime`` imports by name (``LUMI_CHAT_RUNTIME``).

Module-level functions, as the seam asks: ``run_turn``, ``stream_turn``, ``scan_trends`` and
``generate_title``. Each one starts a run (a fresh Xpoz credit meter) and waits for the turn's
background work (memory extraction) before it returns, because the caller's event loop ends
with the request.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Mapping
from typing import Any

from rest_framework import status

from apps.core.errors import ApiError
from apps.intelligence.wiring import begin_run, get_wiring
from lumi_ai.agent import streaming
from lumi_ai.agent.result import SSEEvent, TurnResult
from lumi_ai.agent.streaming import error_payload
from lumi_ai.providers.errors import LLMError
from lumi_ai.tools.registry import ToolContext

log = logging.getLogger(__name__)

TITLE_PROMPT = (
    "Write a chat title of at most five words for the user's first message. "
    "Reply with the title only: no quotes, no final punctuation."
)
TITLE_MAX_CHARS = 60


MESSAGES_ES = {
    "llm_not_configured": "No hay ningún modelo de lenguaje configurado.",
    "llm_unavailable": "Los modelos no responden ahora mismo. Prueba en un momento.",
    "request_too_large": "El mensaje es demasiado largo para los modelos disponibles.",
}


def _unavailable(exc: LLMError) -> ApiError:
    """A provider failure as the API's own error; the detail stays in the server log."""
    log.warning("chat turn failed: %s", exc)
    code = error_payload(exc)["code"]
    return ApiError(
        code,
        MESSAGES_ES.get(code, MESSAGES_ES["llm_unavailable"]),
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
    )


async def run_turn(profile_id: int, message: str) -> TurnResult:
    wiring = get_wiring()
    begin_run(profile_id)
    try:
        return await wiring.loop.run_turn(profile_id, message)
    except LLMError as exc:
        raise _unavailable(exc) from None
    except LookupError:
        raise ApiError(
            "not_found", "Perfil no encontrado.", status_code=status.HTTP_404_NOT_FOUND
        ) from None
    finally:
        await wiring.loop.drain()


async def stream_turn(profile_id: int, message: str) -> AsyncIterator[SSEEvent]:
    wiring = get_wiring()
    begin_run(profile_id)
    try:
        async for event in streaming.stream_turn(wiring.loop, profile_id, message):
            yield event
    finally:
        await wiring.loop.drain()


async def scan_trends(
    profile_id: int, handles: list[str] | None, min_likes: int
) -> Mapping[str, Any]:
    """The ``check_niche_trends`` tool, run for the "scan now" button (no model in between)."""
    wiring = get_wiring()
    spec = wiring.registry.get("check_niche_trends")
    if spec is None:
        return {"error": "trend scanning is not available"}
    begin_run(profile_id)
    return await spec.handler(
        ToolContext(profile_id, wiring.config), handles=handles, min_likes=min_likes
    )


async def generate_title(message: str) -> str | None:
    """A short chat title from the small model; ``None`` lets the route use the first words."""
    wiring = get_wiring()
    if not wiring.chain.providers:
        return None
    try:
        result = await wiring.chain.complete(
            [
                {"role": "system", "content": TITLE_PROMPT},
                {"role": "user", "content": message[:500]},
            ],
            tier="small",
        )
    except Exception as exc:  # noqa: BLE001 - a title is cosmetic; the route has a fallback
        log.warning("chat title failed: %s", exc)
        return None
    title = (result.completion.choices[0].message.content or "").strip().strip("\"'")
    return title[:TITLE_MAX_CHARS] or None
