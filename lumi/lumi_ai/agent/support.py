"""Small pieces of one agent turn: argument parsing, failure text, sample posts, judge timing.

Ported from ``app/agent/loop.py``. Nothing here keeps state between turns.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from lumi_ai.config import AIConfig
from lumi_ai.ports import SemanticJudge
from lumi_ai.providers.chain import LLMResult

logger = logging.getLogger(__name__)


class Completer(Protocol):
    """What the loop needs from the provider chain (``LLMChain`` satisfies it)."""

    async def complete(
        self,
        messages: Sequence[Mapping[str, Any]],
        tools: Sequence[Mapping[str, Any]] | None = None,
        *,
        model: str | None = None,
        tier: str | None = None,
        effort: str | None = None,
    ) -> LLMResult: ...


def parse_tool_arguments(raw: str | None) -> tuple[dict[str, Any], str | None]:
    """Parse a tool call's argument JSON, reporting (never raising) on garbage.

    A malformed blob from the model becomes model-facing feedback so the call can be retried.
    """
    text = raw or "{}"
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        return {}, f"invalid JSON: {exc.msg} at character {exc.pos}"
    if not isinstance(parsed, dict):
        return {}, f"expected a JSON object, got {type(parsed).__name__}"
    return parsed, None


def tool_failure_message(name: str, exc: Exception) -> str:
    """What the model is told when a tool blows up: honest and actionable, no traceback."""
    if isinstance(exc, ValueError):
        # Registry messages are already written for the model (unknown tool, missing args).
        return f"{name} rejected the call: {exc}"
    return (
        f"Tool {name} failed with {type(exc).__name__}: {exc}. "
        "Do not pretend it worked: retry once if it looks transient, otherwise tell the user "
        "which capability is unavailable."
    )


def timeout_message(name: str, seconds: float) -> str:
    return (
        f"Tool {name} timed out after {seconds:g}s "
        "(external service too slow or unreachable). Do not claim it worked: "
        "retry once or tell the user which capability failed."
    )


def timeout_after_write_message(name: str, seconds: float, commits: int) -> str:
    return (
        f"Tool {name} timed out after {seconds:g}s, but {commits} of its database "
        "write(s) had already been saved. Do not claim it fully worked and do not "
        "repeat it blindly: check the current state first or tell the user it may be partial."
    )


def malformed_arguments_message(name: str, parse_error: str) -> str:
    return (
        f"Arguments for {name} were not valid JSON object text ({parse_error}). "
        "Call the tool again with well-formed JSON."
    )


def extract_sample_posts(result: Any, limit: int = 4) -> list[dict[str, Any]]:
    """Up to ``limit`` posts a tool returned, shaped for the chat cards."""
    if not isinstance(result, dict):
        return []
    candidates = result.get("viral_posts") or result.get("posts") or []
    if not isinstance(candidates, list):
        return []
    out: list[dict[str, Any]] = []
    for post in candidates[:limit]:
        if not isinstance(post, dict):
            continue
        out.append(
            {
                "author": post.get("author")
                or post.get("author_handle")
                or post.get("authorUsername"),
                "text": (post.get("caption") or post.get("text") or "")[:120],
                "likes": post.get("likes") or post.get("likeCount"),
                "url": post.get("url") or post.get("platform_url"),
            }
        )
    return out


def tool_failed(result: Any) -> bool:
    return isinstance(result, dict) and bool(result.get("error"))


class TimedJudge:
    """Wraps a judge for ONE turn and adds up the time spent waiting for it.

    A wrapper owned by the turn replaces the legacy module-level contextvar: no hidden state,
    two concurrent turns can never mix their numbers.
    """

    def __init__(self, inner: SemanticJudge) -> None:
        self._inner = inner
        self.elapsed_ms = 0.0

    async def ask_noul(
        self, state: dict[str, Any], questions: dict[str, str]
    ) -> dict[str, float] | None:
        started = time.perf_counter()
        try:
            return await self._inner.ask_noul(state, questions)
        finally:
            self.elapsed_ms += (time.perf_counter() - started) * 1000

    async def ask_choice(
        self,
        state: dict[str, Any],
        name: str,
        instructions: str,
        criteria: dict[str, str],
    ) -> str | None:
        started = time.perf_counter()
        try:
            return await self._inner.ask_choice(state, name, instructions, criteria)
        finally:
            self.elapsed_ms += (time.perf_counter() - started) * 1000


async def enough_information(
    judge: SemanticJudge | None,
    config: AIConfig,
    user_message: str,
    messages: Sequence[Mapping[str, Any]],
) -> bool:
    """Ask the judge whether the tool results gathered so far already answer the request.

    No judge or no verdict means "not enough": the loop keeps going as before.
    """
    if judge is None:
        return False
    snippets = [
        str(m.get("content") or "")[:1500] for m in messages if m.get("role") == "tool"
    ][-6:]
    if not snippets:
        return False
    scores = await judge.ask_noul(
        state={
            "user_request": user_message,
            "gathered_information": "\n---\n".join(snippets),
        },
        questions={
            "sufficient": (
                "Is the gathered information sufficient to fully answer the user's request "
                "without calling any more tools? Only give 1.0 when the answer is clearly "
                "ready; give 0.0 when anything required is still missing."
            ),
        },
    )
    if scores is None or "sufficient" not in scores:
        return False
    return scores["sufficient"] >= config.sufficiency_threshold


async def memory_worthy(
    judge: SemanticJudge | None, config: AIConfig, user_message: str, reply: str
) -> bool:
    """Gate for memory extraction: only turns with durable value. Fails open without a verdict."""
    if judge is None:
        return True
    scores = await judge.ask_noul(
        state={"user_message": user_message[:2000], "assistant_reply": reply[:2000]},
        questions={
            "durable": (
                "Does this exchange contain durable information worth remembering about the "
                "user across sessions (stable preferences, goals, constraints, facts about "
                "their work or audience)? Purely transient requests with no lasting info "
                "should score 0.0."
            ),
        },
    )
    if scores is None or "durable" not in scores:
        return True
    return scores["durable"] >= config.memory_worthy_threshold


async def continue_truncated(
    llm: Completer, messages: list[dict[str, Any]], reply: str
) -> str:
    """``finish_reason=length``: ONE continuation attempt; if it happens again, say so.

    The user must either get the rest of the reply or an honest notice.
    """
    logger.warning(
        "finish_reason=length: reply truncated at %d chars, continuing once", len(reply)
    )
    messages.append({"role": "assistant", "content": reply})
    messages.append(
        {
            "role": "user",
            "content": (
                "Your previous reply was cut off mid-sentence by the response length limit. "
                "Continue exactly where it stopped. Do not repeat anything already written, "
                "do not restart, and do not add a preface."
            ),
        }
    )
    try:
        result = await llm.complete(messages, [])
    except Exception as exc:  # noqa: BLE001 - a failed continuation must never lose the reply
        logger.warning("continuation call failed: %s", exc)
        return (
            reply + "\n\n[Note: this reply was cut off by the response length limit.]"
        )
    choice = result.completion.choices[0]
    part = (choice.message.content or "").strip()
    joined = reply if reply.endswith((" ", "\n")) else reply + " "
    joined += part
    if getattr(choice, "finish_reason", None) == "length":
        logger.warning(
            "finish_reason=length again after continuation, capping the reply"
        )
        return (
            joined
            + '\n\n[cut off again: the reply hit the response length limit — say "next" to continue]'
        )
    return joined
