"""Context management for the agent loop: token budget, tool-result trimming, history note.

Ported from ``app/agent/loop.py``. Limits come from :class:`lumi_ai.config.AIConfig`
instead of module constants.
"""

from __future__ import annotations

import json
import logging
import math
from typing import Any

from lumi_ai.config import AIConfig

logger = logging.getLogger(__name__)


def estimate_tokens(text: str, chars_per_token: float = 3.5) -> int:
    """Crude but consistent token estimate (chars / 3.5).

    Conservative for prose (real tokenizers run ~4 chars/token), a touch low for JSON-heavy
    payloads (~3.3); the provider fallback chain absorbs the miss. Better to trim one message
    early than to bust a provider request wall.
    """
    if not text:
        return 0
    return math.ceil(len(text) / chars_per_token)


def message_token_estimate(
    message: dict[str, Any], chars_per_token: float = 3.5
) -> int:
    """Token estimate for one chat message (content plus any tool_calls payload)."""
    total = estimate_tokens(message.get("content") or "", chars_per_token)
    tool_calls = message.get("tool_calls")
    if tool_calls:
        try:
            total += estimate_tokens(
                json.dumps(tool_calls, default=str), chars_per_token
            )
        except (TypeError, ValueError):
            total += 50  # opaque payload; rough padding beats a crash
    return total


def slim_for_context(tool_name: str, result: Any) -> Any:
    """Shrink bulky tool results before they enter the model context.

    The DB row and the SSE payload keep the full result — this only trims
    what the LLM has to read.
    """
    if (
        tool_name != "get_analytics"
        or not isinstance(result, dict)
        or result.get("error")
    ):
        return result
    slim = {
        k: v for k, v in result.items() if k not in ("reach_series", "saves_series")
    }
    if isinstance(slim.get("allocation"), list):
        slim["allocation"] = [
            {key: entry.get(key) for key in ("label", "pct", "amount")}
            for entry in slim["allocation"]
            if isinstance(entry, dict)
        ]
    if isinstance(slim.get("top_posts"), list):
        slim["top_posts"] = [
            {
                "caption": (entry.get("caption") or "")[:120],
                "impressions": entry.get("impressions"),
                "likes": entry.get("likes"),
            }
            for entry in slim["top_posts"][:3]
            if isinstance(entry, dict)
        ]
    return slim


def build_tools_note(history: list[dict]) -> str:
    """A <=5-line TOOLS USED note from the newest assistant rows (prompt rule 22).

    Newest-first so the most recent turn leads; first 8 tool names per row.
    `.get` keeps test fakes (history dicts without the key) working. Empty
    history / no tool-calling rows -> "" (no message injected).
    """
    lines: list[str] = []
    for msg in reversed(history):
        if msg.get("role") != "assistant":
            continue
        names = msg.get("tools_used")
        if not names:
            continue
        lines.append(f"- {', '.join(str(n) for n in names[:8])}")
        if len(lines) >= 5:
            break
    if not lines:
        return ""
    return (
        "TOOLS USED (from earlier turns; answer tool-history questions from this "
        "note, never by re-running tools):\n" + "\n".join(lines)
    )


def fit_messages(
    messages: list[dict],
    history_start: int,
    user_idx: int,
    tools_tokens: int,
    config: AIConfig | None = None,
) -> int:
    """Trim the assembled request until it fits ``AIConfig.max_request_tokens``.

    Regions: [0, history_start) = system prompt(s), never touched;
    [history_start, user_idx) = older history, the only droppable region;
    [user_idx, ...) = the current user message plus everything appended this
    turn (claim-gate nudge, assistant tool_calls, tool results) — protected
    except for the dedicated tool-group ladder below.

    Ladder, each rung only while still over budget:
    1. drop the oldest old-history message;
    2. shrink tool contents in every group except the newest to
       cfg.old_tool_context_char_limit;
    3. drop the oldest whole tool group (assistant tool_calls + its tool
       responses together, so no orphaned tool_call reaches the API).

    The system prompt, the current user message, and the NEWEST tool group are
    never dropped. Still over budget after the ladder means the request is sent
    as-is: the provider chain (Groq fallback model, then OpenRouter) may still
    accept it, and an honest failure beats silently truncating the user's own
    words. Returns the updated current-message index (unchanged unless rung 1
    removed history ahead of it).
    """
    cfg = config or AIConfig()
    cpt = cfg.est_chars_per_token
    budget = max(cfg.max_request_tokens - tools_tokens, 500)

    def _total() -> int:
        # Messages-only: the budget already has tools_tokens subtracted.
        return sum(message_token_estimate(m, cpt) for m in messages)

    # Rung 1: drop the oldest history first.
    dropped_history = 0
    while user_idx > history_start and _total() > budget:
        del messages[history_start]
        user_idx -= 1
        dropped_history += 1

    def _tool_groups() -> list[tuple[int, int]]:
        # Any assistant message carrying tool_calls is from THIS turn — history
        # rows are built role/content-only and never carry them — so no index
        # guard is needed (and none is safe: with an empty history the first
        # appended message lands exactly AT user_idx).
        starts = [
            i
            for i, m in enumerate(messages)
            if m.get("role") == "assistant" and m.get("tool_calls")
        ]
        bounds = starts + [len(messages)]
        return [(bounds[i], bounds[i + 1]) for i in range(len(starts))]

    groups = _tool_groups()
    dropped_groups = 0
    while _total() > budget and len(groups) > 1:
        # Rung 2: shrink tool contents in every group but the newest.
        for start, end in groups[:-1]:
            for m in messages[start:end]:
                if (
                    m.get("role") == "tool"
                    and isinstance(m.get("content"), str)
                    and len(m["content"]) > cfg.old_tool_context_char_limit
                ):
                    m["content"] = (
                        m["content"][: cfg.old_tool_context_char_limit]
                        + " ...[older tool result trimmed]"
                    )
        if _total() <= budget:
            break
        # Rung 3: drop the oldest whole tool group.
        start, end = groups[0]
        del messages[start:end]
        dropped_groups += 1
        groups = _tool_groups()

    if dropped_history or dropped_groups:
        logger.info(
            "context budget: dropped %d oldest history message(s) and %d old tool group(s) to fit",
            dropped_history,
            dropped_groups,
        )
    if _total() > budget:
        logger.info(
            "context over budget after trimming (%d est tokens > %d); sending as-is — "
            "provider model fallback may still accept it",
            _total(),
            budget,
        )
    return user_idx


def clip_tool_content(text: str, config: AIConfig) -> str:
    """Hard cap on a tool result sent into the model context (the database keeps the full text)."""
    limit = config.tool_context_char_limit
    return text if len(text) <= limit else text[:limit] + " ...[truncated]"
