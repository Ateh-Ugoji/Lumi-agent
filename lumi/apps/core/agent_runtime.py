"""The seam between the API routes and the agent (``apps.intelligence.runtime``).

The chat and trends routes may not import ``intelligence`` at module level (it would be a cycle, and the agent is
optional while it is being built). The runtime is a module or object with:

* ``async run_turn(profile_id, message) -> TurnResult``
* ``stream_turn(profile_id, message) -> AsyncIterator[SSEEvent]``
* ``async generate_title(message) -> str | None`` (optional; the route falls back to the first words)
* ``async scan_trends(profile_id, handles, min_likes) -> Mapping`` (the ``check_niche_trends`` tool result)

It comes from ``set_runtime`` (tests, or INTELLIGENCE's ``ready()``) or else from the dotted path
in ``settings.LUMI_CHAT_RUNTIME``. When neither works the routes answer 503 ``chat.unavailable``.
"""

from __future__ import annotations

import importlib
import logging
from collections.abc import AsyncIterator, Mapping
from typing import Any, Protocol

from django.conf import settings
from rest_framework import status

from apps.core.errors import ApiError
from lumi_ai.agent.result import SSEEvent, TurnResult

logger = logging.getLogger(__name__)

DEFAULT_RUNTIME = "apps.intelligence.runtime"


class ChatRuntime(Protocol):
    async def run_turn(self, profile_id: int, message: str) -> TurnResult: ...

    def stream_turn(self, profile_id: int, message: str) -> AsyncIterator[SSEEvent]: ...

    async def scan_trends(
        self, profile_id: int, handles: list[str] | None, min_likes: int
    ) -> Mapping[str, Any]: ...


_runtime: Any = None


def set_runtime(runtime: Any | None) -> None:
    """Install (or with ``None`` clear) the runtime. Idempotent."""
    global _runtime
    _runtime = runtime


def get_runtime() -> ChatRuntime:
    if _runtime is not None:
        return _runtime
    path = getattr(settings, "LUMI_CHAT_RUNTIME", DEFAULT_RUNTIME)
    try:
        module = importlib.import_module(path)
    except ImportError:
        logger.warning("chat runtime %s is not importable", path)
        raise ApiError(
            "chat.unavailable",
            "El asistente no está disponible por ahora.",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        ) from None
    if not (hasattr(module, "run_turn") and hasattr(module, "stream_turn")):
        logger.warning("chat runtime %s lacks run_turn/stream_turn", path)
        raise ApiError(
            "chat.unavailable",
            "El asistente no está disponible por ahora.",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    return module  # type: ignore[return-value]


def fallback_title(message: str) -> str:
    """First four words, title-cased. Same fallback as the legacy route."""
    words = message.strip().split()
    return " ".join(words[:4]).title() or "New Chat"


async def make_title(message: str) -> str:
    """Ask the runtime for a title; any failure or odd answer falls back to the first words."""
    try:
        generate = getattr(get_runtime(), "generate_title", None)
        raw = await generate(message) if generate else None
    except Exception:
        logger.warning("title generation failed", exc_info=True)
        raw = None
    title = (
        (raw or "")
        .strip()
        .strip("\"'")
        .replace("**", "")
        .replace("#", "")
        .replace(".", "")
        .strip()
    )
    return title if title and len(title) <= 35 else fallback_title(message)
