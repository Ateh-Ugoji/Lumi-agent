"""Jev (TypeSafe AI) decision layer.

One shared client per event loop: connection reuse cuts a call from ~1.5s
(per-call client) to ~450ms warm. Every helper returns None on any failure
so callers always fall back to their deterministic/LLM path.

Jev answers structured questions only (Noul = 0..1 score, Choice = label);
it never generates text.
"""

import asyncio
import contextvars
import logging
import time
from typing import Any

from typesafe_sdk import AsyncTypeSafeClient, Choice, Noul, TypeSafeError

from app.config import get_settings

log = logging.getLogger(__name__)

_clients: dict[int, AsyncTypeSafeClient] = {}

# Per-turn Jev latency accumulator (context-local, so concurrent turns in
# different tasks don't mix). The agent loop resets it and reports the total.
_turn_ms: contextvars.ContextVar[float] = contextvars.ContextVar("jev_turn_ms", default=0.0)


def reset_turn_timing() -> None:
    _turn_ms.set(0.0)


def turn_timing_ms() -> float:
    return _turn_ms.get()


def _client() -> AsyncTypeSafeClient:
    """Lazy shared client, keyed by running event loop (tests get their own)."""
    loop_key = id(asyncio.get_running_loop())
    client = _clients.get(loop_key)
    if client is None:
        client = AsyncTypeSafeClient(api_key=get_settings().typesafe_api_key)
        _clients[loop_key] = client
    return client


async def ask(state: dict[str, Any], questions: dict[str, Noul | Choice]) -> dict[str, Any] | None:
    """Run one system_one call.

    Returns {question_name: noul_score (float) or choice (str)} — or None if
    Jev is unavailable/misconfigured. Never raises.
    """
    started = time.perf_counter()
    try:
        result = await _client().system_one(state=state, questions=questions)
    except TypeSafeError as exc:
        log.warning("Jev unavailable: %s", exc)
        return None
    except Exception as exc:  # noqa: BLE001 — Jev is best-effort everywhere
        log.warning("Jev call failed: %s", exc)
        return None
    finally:
        _turn_ms.set(_turn_ms.get() + (time.perf_counter() - started) * 1000)
    log.debug("jev ask %.0fms %s", (time.perf_counter() - started) * 1000, list(questions))
    out: dict[str, Any] = {}
    for name, answer in result.answers.items():
        choice = getattr(answer, "choice", None)
        out[name] = choice if choice is not None else float(answer.noul)
    return out


async def ask_noul(state: dict[str, Any], questions: dict[str, str]) -> dict[str, float] | None:
    """Score questions: {name: instructions} -> {name: 0..1} or None."""
    res = await ask(state, {name: Noul(instructions=instr) for name, instr in questions.items()})
    if res is None:
        return None
    try:
        return {name: float(value) for name, value in res.items()}
    except (TypeError, ValueError):
        return None


async def ask_choice(
    state: dict[str, Any],
    name: str,
    instructions: str,
    criteria: dict[str, str],
) -> str | None:
    """Label question -> chosen criterion key or None."""
    res = await ask(state, {name: Choice(instructions=instructions, criteria=criteria)})
    if res is None:
        return None
    value = res.get(name)
    return value if isinstance(value, str) else None
