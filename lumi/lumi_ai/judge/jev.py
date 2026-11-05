"""Jev (TypeSafe AI) as a :class:`~lumi_ai.ports.SemanticJudge`.

Jev answers structured questions only (Noul = 0..1 score, Choice = label); it never writes
text. One client per running event loop: connection reuse cuts a call from ~1.5 s (client per
call) to ~450 ms warm. Every failure returns ``None`` so the caller falls back.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from lumi_ai.config import AIConfig

log = logging.getLogger(__name__)


class JevJudge:
    """Judge backed by the TypeSafe SDK. Without ``TYPESAFE_API_KEY`` every answer is ``None``."""

    def __init__(self, config: AIConfig, *, client_factory: Any = None) -> None:
        self._api_key = config.typesafe_api_key
        self._client_factory = client_factory
        self._clients: dict[int, Any] = {}

    @property
    def available(self) -> bool:
        return bool(self._api_key) or self._client_factory is not None

    def _client(self) -> Any:
        key = id(asyncio.get_running_loop())
        client = self._clients.get(key)
        if client is None:
            if self._client_factory is not None:
                client = self._client_factory()
            else:
                from typesafe_sdk import AsyncTypeSafeClient

                client = AsyncTypeSafeClient(api_key=self._api_key)
            self._clients[key] = client
        return client

    async def _ask(
        self, state: dict[str, Any], questions: dict[str, Any]
    ) -> dict[str, Any] | None:
        if not self.available:
            return None
        try:
            result = await self._client().system_one(state=state, questions=questions)
            out: dict[str, Any] = {}
            for name, answer in result.answers.items():
                choice = getattr(answer, "choice", None)
                out[name] = choice if choice is not None else float(answer.noul)
            return out
        except Exception as exc:  # noqa: BLE001 - Jev is best-effort everywhere
            log.warning("Jev call failed: %s", exc)
            return None

    async def ask_noul(
        self, state: dict[str, Any], questions: dict[str, str]
    ) -> dict[str, float] | None:
        if not self.available:
            return None
        from typesafe_sdk import Noul

        res = await self._ask(
            state, {name: Noul(instructions=text) for name, text in questions.items()}
        )
        if res is None:
            return None
        try:
            return {name: float(value) for name, value in res.items()}
        except (TypeError, ValueError):
            return None

    async def ask_choice(
        self,
        state: dict[str, Any],
        name: str,
        instructions: str,
        criteria: dict[str, str],
    ) -> str | None:
        if not self.available:
            return None
        from typesafe_sdk import Choice

        res = await self._ask(
            state, {name: Choice(instructions=instructions, criteria=criteria)}
        )
        value = (res or {}).get(name)
        return value if isinstance(value, str) and value in criteria else None
