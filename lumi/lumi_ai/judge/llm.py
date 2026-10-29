"""Fallback judges: a small LLM scores the same questions, and a chain tries judges in order."""

from __future__ import annotations

import json
import logging
from typing import Any

from lumi_ai.json_utils import JSONExtractionError, extract_json_object
from lumi_ai.ports import SemanticJudge
from lumi_ai.providers.chain import LLMChain

log = logging.getLogger(__name__)

_NOUL_SYSTEM = (
    "You are a strict classifier. You receive a JSON state and a set of questions. "
    "Answer EVERY question with a number from 0.0 to 1.0 (1.0 = clearly yes, 0.0 = clearly no). "
    "Reply with ONE JSON object mapping each question name to its number, nothing else."
)
_CHOICE_SYSTEM = (
    "You are a strict classifier. You receive a JSON state, a question and a set of criteria. "
    "Pick exactly one criterion key. "
    'Reply with ONE JSON object {"choice": "<criterion key>"}, nothing else.'
)


class LLMJudge:
    """Judge that asks the small-tier LLM of the provider chain. Used when Jev is unavailable."""

    def __init__(self, chain: LLMChain, *, tier: str = "small") -> None:
        self._chain = chain
        self._tier = tier

    async def _complete(
        self, system: str, user: dict[str, Any]
    ) -> dict[str, Any] | None:
        messages = [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": json.dumps(user, ensure_ascii=False, default=str),
            },
        ]
        try:
            result = await self._chain.complete(
                messages, [], tier=self._tier, effort="low"
            )
            text = result.completion.choices[0].message.content or ""
            return extract_json_object(text)
        except JSONExtractionError as exc:
            log.warning("LLM judge returned unparseable output: %s", exc)
        except Exception as exc:  # noqa: BLE001 - the judge is best-effort
            log.warning("LLM judge failed: %s", exc)
        return None

    async def ask_noul(
        self, state: dict[str, Any], questions: dict[str, str]
    ) -> dict[str, float] | None:
        data = await self._complete(
            _NOUL_SYSTEM, {"state": state, "questions": questions}
        )
        if data is None:
            return None
        scores: dict[str, float] = {}
        for name in questions:
            try:
                scores[name] = min(1.0, max(0.0, float(data[name])))
            except (KeyError, TypeError, ValueError):
                return None  # a partial verdict is no verdict
        return scores

    async def ask_choice(
        self,
        state: dict[str, Any],
        name: str,
        instructions: str,
        criteria: dict[str, str],
    ) -> str | None:
        data = await self._complete(
            _CHOICE_SYSTEM,
            {"state": state, "question": instructions, "criteria": criteria},
        )
        value = (data or {}).get("choice")
        return value if isinstance(value, str) and value in criteria else None


class FallbackJudge:
    """Tries each judge in order and returns the first verdict; ``None`` when all abstain."""

    def __init__(self, *judges: SemanticJudge) -> None:
        self._judges = judges

    async def ask_noul(
        self, state: dict[str, Any], questions: dict[str, str]
    ) -> dict[str, float] | None:
        for judge in self._judges:
            verdict = await judge.ask_noul(state, questions)
            if verdict is not None:
                return verdict
        return None

    async def ask_choice(
        self,
        state: dict[str, Any],
        name: str,
        instructions: str,
        criteria: dict[str, str],
    ) -> str | None:
        for judge in self._judges:
            verdict = await judge.ask_choice(state, name, instructions, criteria)
            if verdict is not None:
                return verdict
        return None
