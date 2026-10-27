import asyncio
import json
import math
import re
import time
from dataclasses import dataclass, field

import neatlogs
from sqlmodel import select

from app.agent.prompts import build_fast_prompt, build_system_prompt
from app.agent.providers import chat_completion_with_fallback

# Turn classifier: rule-based class -> allowed tool tiers, optional Jev stage 2.
# (is_greeting_only is re-exported here so existing importers keep working.)
from app.agent.turn_class import (
    CHITCHAT,
    HISTORY_META,
    MEMORY,
    READ_CHEAP,
    allowed_for,
    classify_turn,
    is_greeting_only,
    log_hash,
    log_preview,
)
from app.database import session_scope
from app.models.chat import ChatMessage, ChatRole
from app.models.profile import Profile
from app.models.turn_classification import TurnClassification
from app.services import jev
from app.services import mcp as mcp_service
from app.services.memory import extract_turn_memories, get_profile_summary
from app.tools import registry as tool_registry

MAX_TOOL_ITERATIONS = 6
# Jev sufficiency gate: after >=2 tool calls, ask whether we already have enough
# to answer. >= threshold forces the final synthesis call with no tools.
SUFFICIENCY_THRESHOLD = 0.75
SUFFICIENCY_MIN_TOOLS = 2


import logging
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)



@dataclass
class AgentResult:
    content: str
    tool_calls_made: list[str] = field(default_factory=list)
    tool_executions: list[dict] = field(default_factory=list)
    path_taken: str = "full"  # "fast" (chitchat, no tools) | "full"
    # Stays None at return: the classification row is written fire-and-forget.
    classification_id: int | None = None


# Classes that run with reasoning_effort="low" on the completion call (same set
# as turn_class.FREE_TIER_CLASSES — defined locally so the "effort tier" concept
# never gets conflated with the "credit tier" one).
_LOW_EFFORT_CLASSES = frozenset({CHITCHAT, HISTORY_META, MEMORY, READ_CHEAP})


MAX_HISTORY_MESSAGES = 10

# Hard cap on a tool result sent into the model context (DB keeps the full text).
TOOL_CONTEXT_CHAR_LIMIT = 4000

# Older tool groups (every group but the newest) shrink to this before any
# whole group is dropped — see _fit_messages.
OLD_TOOL_CONTEXT_CHAR_LIMIT = 1200

# --- request-size budget -----------------------------------------------------
# Groq walls (measured 2026-10-21): qwen3.8-27b rejects requests over ~7,000
# input tokens (413 request-too-large), openai/gpt-oss-120b over ~8,000. Fixed
# overhead (system prompt + tool specs) is ~5,700 estimated tokens, so this
# budget targets the FIRST completion staying under qwen's wall; tool-heavy
# turns may still exceed it and ride the gpt-oss-120b fallback (providers.py).
# Estimation is chars/3.5 — conservative for prose (~4 chars/token real), a
# touch low for JSON (~3.3); misses are absorbed by the model fallback chain.
# A single user paste of >~8k tokens exceeds every wall: the turn then fails
# honestly rather than silently truncating the user's own words.
MAX_REQUEST_TOKENS = 6_700
EST_CHARS_PER_TOKEN = 3.5

# Whitelist of greeting-only phrases moved to app/agent/turn_class.py (the
# turn classifier shares it); `is_greeting_only` is imported above.


# --- action-claim gate ------------------------------------------------------
# A model turn that claims work was done/running (or promises to do it next)
# while having called ZERO tools is fabrication. One corrective nudge is
# injected; if the model still claims without acting, an honest disclaimer is
# appended to the reply the user sees.
TOOL_TIMEOUT_SECONDS = 120  # one hung external call must never kill the turn

_COMPLETED_ACTION_PATTERNS = (
    r"\bi'?ve (finished|completed|run|dug)\b",
    r"\bfinished digging\b",
    r"\bdone digging\b",
    r"\bi ran (a |the |your )?(fresh )?(recon|scan|search|analysis)\b",
    r"\brunning a fresh (recon|scan|search)\b",
    r"\bi'?m (now )?(running|digging|scanning|analyzing)\b",
    r"\b(results|recon) (are|is) (in|ready|done|complete)\b",
    r"\bfresh (numbers|data|stats|results|findings)\b",
    # past-tense save/record claims — observed live: "I had saved @x as your user
    # request, so that part went through" with zero tools called. The leading
    # `\bi` must accept "I've/I'd/I have/I had/I <verb>" WITHOUT a space before
    # the auxiliaries ("I've" has no space after the I).
    r"\bi(?:'ve |'d | have | had | )(?:already )?(?:saved|recorded|logged|stored)\b",
    r"\b(?:that part |it |they |those )?went through\b",
    # doc/file creation claims with zero tools ("I created the doc", "I've
    # drafted the document") — MCP write tools require a confirmation round-trip,
    # so such a claim without any tool call is fabrication by construction
    r"\bi(?:'ve |'d | have | had | )(?:already )?(?:created|made|wrote|drafted)\b[^\n]{0,60}\b(?:doc|document|files?|draft)\b",
)
_PROMISE_ACTION_PATTERNS = (
    r"\bi'?ll (run|do a|do the|start|kick off|launch)\b[^\n]{0,60}\b(recon|scan|search|analysis)\b",
    r"\bi'?ll (run|scan|search)\b[^\n]{0,40}\b(through|for|on)\b",
    r"\blet me (run|scan|search|dig)\b",
)
_ACTION_CLAIM_RE = re.compile(
    "|".join(f"(?:{p})" for p in _COMPLETED_ACTION_PATTERNS + _PROMISE_ACTION_PATTERNS),
    re.IGNORECASE,
)
# The USER's message explicitly demanding a data-fetch action. Reply-wording
# patterns are evasive (the model keeps inventing phrasings like "Good, fresh
# numbers now"), so the user side of the conversation gates too: a command to
# search/scan + zero tools = fabrication unless the reply honestly declines.
_ACTION_REQUEST_RE = re.compile(
    r"\b(?:search|scan|recon|look\s?up"
    r"|pull\s+(?:the\s+)?(?:latest|recent|fresh|numbers|data|stats)"
    r"|check\s+(?:the\s+)?(?:trends|stats|numbers|analytics|data|peers?|niche)"
    r"|fetch"
    # MCP doc/drive requests: "make a doc", "create a new Google Doc", "draft a
    # document", "list my Drive files" — a zero-tool reply to these fabricates
    r"|(?:create|make|write|draft|open)\s+(?:a\s+|an\s+|the\s+)?(?:new\s+)?(?:google\s+)?(?:doc|document|file)s?"
    r"|(?:list|show|find)\b[^\n]{0,40}\b(?:drive|files?)"
    r")\b",
    re.IGNORECASE,
)
# A message that is NOTHING but tagged handles ("@beaconsai", "@a & @b") — the
# user tagged an account from the composer's @ menu and sent it as-is. That is
# a lookup request by construction (prompt rule 13).
_BARE_HANDLES_RE = re.compile(r"^\s*(?:@[A-Za-z0-9_]{1,15}[.,]?\s*[,&]?\s*)+$")
# Tier-2 reply phrasing: presenting fresh data without a concrete past-action
# claim ("Here's what's working right now for @beaconsai" with zero tools).
_PRESENTING_RE = re.compile(
    r"\bhere'?s what(?:'s| is)? (?:working|happening|trending)\b",
    re.IGNORECASE,
)
# Honest markers (no nudge, no disclaimer): replies that admit they cannot do
# the work, OR that explicitly label their content as stored/standing data
# (prompt rule 15's compliant framing of get_peer_advice results).
_DECLINE_RE = re.compile(
    r"\b(?:can'?t|cannot|couldn'?t|unable|not able|don'?t have|do not have"
    r"|no access|haven'?t|didn'?t run|not actually run|timed out|failed"
    r"|blocked|doesn'?t work|does not work"
    # connector not connected is an honest decline too ("Google isn't connected")
    r"|not (?:yet )?connected|isn'?t connected|is not connected|connect (?:it |google |them )?first"
    r"|(?:stored|standing) (?:advice|recon|analysis|picture|data|patterns))\b",
    re.IGNORECASE,
)
_NO_TOOL_NUDGE = (
    "System reminder for this turn only: you have not called any tool yet. Do not describe "
    "work as done, running, or found unless a tool actually produced it this turn. If the "
    "user's request needs data, call the needed tool(s) NOW and answer from their results. "
    "If you genuinely cannot do it, say plainly what you cannot do and why."
)
_HONESTY_DISCLAIMER = (
    "\n\nCorrection: I have not actually run any scan, recon, or search for this message, "
    "so any claims above about finished or running work are unverified."
)

# --- coverage evidence gate (prompt rules 17/18 — the Beacons failure, L10) ---
# Only @-tagged tokens count as user-named handles (rule-13 normalization: strip
# @, lowercase, unique) — a bare noun is not a handle.
_HANDLE_TAG_RE = re.compile(r"(?<![\w@])@([A-Za-z0-9_]{1,15})\b")
# A deliverable ask (plan/strategy/analysis/…) or a peer-discovery ask. Combined
# with a named handle these make the turn a recon request the evidence gate covers.
_DELIVERABLE_RE = re.compile(
    r"\b(?:plan|strategy|analysis|comparison|breakdown|outline|calendar|schedule|audit|report)\b"
    r"|(?:find|discover|who are|list)\b[^\n]{0,40}\bpeers?\b",
    re.IGNORECASE,
)
# "full picture" family — stripped from any reply whose coverage is incomplete.
_FULL_PICTURE_RE = re.compile(r"\b(?:full|complete|entire|whole)\s+picture\b", re.IGNORECASE)

_COVERAGE_NUDGE = (
    "System reminder for this turn only: you have NOT yet scanned these handles the user named: "
    "{handles}. Call check_niche_trends with exactly those handles NOW, then answer beginning with "
    "the coverage line (rule 17: scanned (n posts) / failed (why) / not run, one per handle). Never "
    "present a plan or findings for a handle you have not scanned."
)


def _extract_named_handles(user_message: str) -> list[str]:
    """@-tagged handles from the user's message, normalized and de-duplicated."""
    return list(dict.fromkeys(m.lower() for m in _HANDLE_TAG_RE.findall(user_message or "")))


def _coverage_required(user_message: str) -> bool:
    """L10 trigger: names at least one handle AND asks for a scan or a deliverable."""
    if not _extract_named_handles(user_message):
        return False
    text = user_message or ""
    return bool(_ACTION_REQUEST_RE.search(text) or _DELIVERABLE_RE.search(text))


def _record_scan_coverage(coverage: dict[str, str], arguments: dict, result: Any) -> None:
    """Fold one check_niche_trends call's outcome into per-handle coverage.

    coverage values: "scanned (n posts)" | "failed (why)" | "not_run". Only
    handles the USER named are tracked — scans of other handles are ignored.
    """
    requested = [str(h).lstrip("@").lower() for h in (arguments or {}).get("handles") or []]
    failed: dict[str, str] = {}
    for entry in (result or {}).get("failed_handles") or []:
        handle, sep, reason = str(entry).partition(":")
        if sep:
            failed[handle.strip().lstrip("@").lower()] = reason.strip() or "lookup failed"
    scanned: dict = (result or {}).get("scanned_handles") or {}
    error = str((result or {}).get("error") or "")
    for handle in requested:
        if handle not in coverage:
            continue
        if handle in failed:
            coverage[handle] = f"failed ({failed[handle][:120]})"
        elif handle in scanned:
            coverage[handle] = f"scanned ({scanned[handle]} posts)"
        elif error:
            coverage[handle] = f"failed ({error[:120]})"


def _coverage_block(coverage: dict[str, str], peers_discovered: bool, frameworks: dict | None) -> str:
    """The rule-17 coverage line — always first in an incomplete-coverage reply."""
    parts = [f"@{handle}: {status}" for handle, status in coverage.items()]
    parts.append(f"peers discovered: {'run' if peers_discovered else 'not run'}")
    if frameworks and frameworks.get("found"):
        niche = str(frameworks.get("niche_title") or "unknown niche")
        age = frameworks.get("age_days")
        line = f"frameworks used: stored {niche} set"
        if age is not None:
            line += f", {age}d old"
        source = {str(h).lower() for h in frameworks.get("source_handles") or []}
        overlap = any(h in source for h in coverage)
        parts.append(line + (", covers the named accounts" if overlap else ", different accounts than named"))
    else:
        parts.append("frameworks used: none this turn")
    return "Recon coverage: " + " | ".join(parts)


async def _continue_truncated(messages: list[dict], reply: str) -> str:
    """finish_reason=length: ONE continuation attempt; if it happens again, say so.

    Observed live: a 7,163-char plan ended mid-sentence ("If a post takes ") and
    the loop never noticed. The user must either get the rest or an honest notice.
    """
    logger.warning("finish_reason=length: reply truncated at %d chars, continuing once", len(reply))
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
        continuation = await chat_completion_with_fallback(messages, [])
    except Exception as exc:  # noqa: BLE001 - a failed continuation must never lose the reply
        logger.warning("continuation call failed: %s", exc)
        return reply + "\n\n[Note: this reply was cut off by the response length limit.]"
    part = (continuation.choices[0].message.content or "").strip()
    joined = reply if reply.endswith((" ", "\n")) else reply + " "
    joined += part
    if getattr(continuation.choices[0], "finish_reason", None) == "length":
        logger.warning("finish_reason=length again after continuation, capping the reply")
        return (
            joined
            + "\n\n[cut off again: the reply hit the response length limit — say \"next\" to continue]"
        )
    return joined


def _claims_action_without_tools(reply: str, tools_ran: bool) -> bool:
    """True when the reply claims/promises scan-style work but no tool ran this turn."""
    if tools_ran:
        return False
    return bool(_ACTION_CLAIM_RE.search(reply or ""))


def _should_nudge(user_message: str, reply: str, tools_ran: bool) -> bool:
    """Fabrication predicate (gate + disclaimer share it): does this zero-tool
    reply fabricate scan-style work?

    Precedence:
    1. An explicit completed/past-action claim fires EVEN IF the reply also
       contains decline wording (observed live: a model sandwiched "I had saved
       @x as your user request, so that part went through" inside "I can't
       cleanly finish this turn" — the claim must win).
    2. Otherwise an honest marker (decline, or explicit stored/standing-data
       labeling per prompt rule 15) passes.
    3. Otherwise fire when the user asked for the action (search/scan/recon
       verbs, or a bare @handle tag) or the reply presents fresh data
       ("Here's what's working…") — on a zero-tool turn that is fabrication
       by construction.
    """
    if tools_ran:
        return False
    text = reply or ""
    if _ACTION_CLAIM_RE.search(text):
        return True
    if _DECLINE_RE.search(text):
        return False
    if _PRESENTING_RE.search(text):
        return True
    if _ACTION_REQUEST_RE.search(user_message or ""):
        return True
    return bool(_BARE_HANDLES_RE.match(user_message or ""))


def _slim_for_context(tool_name: str, result: Any) -> Any:
    """Shrink bulky tool results before they enter the model context.

    The DB row and the SSE payload keep the full result — this only trims
    what the LLM has to read.
    """
    if tool_name != "get_analytics" or not isinstance(result, dict) or result.get("error"):
        return result
    slim = {k: v for k, v in result.items() if k not in ("reach_series", "saves_series")}
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


def _estimate_tokens(text: str) -> int:
    """Crude but consistent token estimate (chars / 3.5).

    Conservative for prose (real tokenizers run ~4 chars/token), a touch low
    for JSON-heavy payloads (~3.3) — the model fallback chain absorbs the miss.
    Better to trim one message early than to bust a provider request wall.
    """
    if not text:
        return 0
    return math.ceil(len(text) / EST_CHARS_PER_TOKEN)


def _message_token_estimate(message: dict) -> int:
    """Token estimate for one chat message (content plus any tool_calls payload)."""
    total = _estimate_tokens(message.get("content") or "")
    tool_calls = message.get("tool_calls")
    if tool_calls:
        try:
            total += _estimate_tokens(json.dumps(tool_calls, default=str))
        except (TypeError, ValueError):
            total += 50  # opaque payload; rough padding beats a crash
    return total


def _fit_messages(
    messages: list[dict],
    history_start: int,
    user_idx: int,
    tools_tokens: int,
) -> int:
    """Trim the assembled request until it fits MAX_REQUEST_TOKENS.

    Regions: [0, history_start) = system prompt(s), never touched;
    [history_start, user_idx) = older history, the only droppable region;
    [user_idx, ...) = the current user message plus everything appended this
    turn (claim-gate nudge, assistant tool_calls, tool results) — protected
    except for the dedicated tool-group ladder below.

    Ladder, each rung only while still over budget:
    1. drop the oldest old-history message;
    2. shrink tool contents in every group except the newest to
       OLD_TOOL_CONTEXT_CHAR_LIMIT;
    3. drop the oldest whole tool group (assistant tool_calls + its tool
       responses together, so no orphaned tool_call reaches the API).

    The system prompt, the current user message, and the NEWEST tool group are
    never dropped. Still over budget after the ladder means the request is sent
    as-is: the provider chain (qwen -> gpt-oss-120b -> OpenRouter) may still
    accept it, and an honest failure beats silently truncating the user's own
    words. Returns the updated current-message index (unchanged unless rung 1
    removed history ahead of it).
    """
    budget = max(MAX_REQUEST_TOKENS - tools_tokens, 500)

    def _total() -> int:
        # Messages-only: the budget already has tools_tokens subtracted.
        return sum(_message_token_estimate(m) for m in messages)

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
                    and len(m["content"]) > OLD_TOOL_CONTEXT_CHAR_LIMIT
                ):
                    m["content"] = (
                        m["content"][:OLD_TOOL_CONTEXT_CHAR_LIMIT]
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


async def _enough_information(user_message: str, messages: list[dict]) -> bool:
    """Ask Jev whether the tool results gathered so far are enough to answer."""
    tool_snippets = [
        str(m.get("content") or "")[:1500]
        for m in messages
        if m.get("role") == "tool"
    ][-6:]
    if not tool_snippets:
        return False
    scores = await jev.ask_noul(
        state={
            "user_request": user_message,
            "gathered_information": "\n---\n".join(tool_snippets),
        },
        questions={
            "sufficient": (
                "Is the gathered information sufficient to fully answer the user's request "
                "without calling any more tools? Only give 1.0 when the answer is clearly "
                "ready; give 0.0 when anything required is still missing."
            ),
        },
    )
    if scores is None:
        return False
    return scores["sufficient"] >= SUFFICIENCY_THRESHOLD

# Keep references to fire-and-forget memory extraction tasks so they aren't GC'd
_memory_tasks: set = set()

MEMORY_WORTHY_THRESHOLD = 0.6


async def _gated_memory_extraction(
    profile_id: int, user_message: str, reply: str, handle: str = ""
) -> None:
    """Jev gate: only extract memories from turns with durable, lasting value.

    Fails open — when Jev is unavailable we extract as before.
    """
    scores = await jev.ask_noul(
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
    if scores is not None and scores["durable"] < MEMORY_WORTHY_THRESHOLD:
        logger.info("memory gate: skipping extraction (durable=%.2f)", scores["durable"])
        return
    await extract_turn_memories(profile_id, user_message, reply, handle=handle)


def _schedule_memory_extraction(
    profile_id: int, user_message: str, reply: str, handle: str = ""
) -> None:
    """Extract durable memories after a turn (async, never blocks or raises)."""
    if not reply or not reply.strip():
        return
    try:
        task = asyncio.create_task(
            _gated_memory_extraction(profile_id, user_message, reply, handle=handle)
        )
        _memory_tasks.add(task)

        def _done(t: "asyncio.Task") -> None:
            _memory_tasks.discard(t)
            if not t.cancelled() and t.exception() is not None:
                logger.warning("memory extraction task failed: %s", t.exception())

        task.add_done_callback(_done)
    except Exception as exc:  # noqa: BLE001
        logger.debug("could not schedule memory extraction: %s", exc)


# Keep references to fire-and-forget classification rows so they aren't GC'd
# (same pattern as _memory_tasks). A failed write must NEVER touch the turn.
_classification_tasks: set = set()


async def _write_classification(row: TurnClassification) -> None:
    try:
        async with session_scope() as session:
            session.add(row)
            await session.commit()
    except Exception as exc:  # noqa: BLE001
        logger.debug("classification row write skipped: %s", exc)


def _schedule_classification(row: TurnClassification) -> None:
    """Persist the classification row after the reply (held task, never raises)."""
    try:
        task = asyncio.create_task(_write_classification(row))
        _classification_tasks.add(task)
        task.add_done_callback(_classification_tasks.discard)
    except Exception as exc:  # noqa: BLE001
        logger.debug("could not schedule classification write: %s", exc)


def _build_tools_note(history: list[dict]) -> str:
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


async def _load_history(profile_id: int) -> list[dict]:
    """Load recent chat history for the LLM context window.

    Only loads the last MAX_HISTORY_MESSAGES user/assistant messages (no tool
    messages, no empty messages).  Too much stale history overwhelms the LLM
    and causes it to return empty content.
    """
    async with session_scope() as session:
        messages = (
            await session.exec(
                select(ChatMessage)
                .where(ChatMessage.profile_id == profile_id, ChatMessage.role != ChatRole.TOOL)
                .order_by(ChatMessage.created_at.desc())
                .limit(MAX_HISTORY_MESSAGES)
            )
        ).all()

    # Reverse back to chronological order (we fetched newest-first)
    messages = list(reversed(messages))

    return [
        {"role": m.role.value, "content": m.content, "tools_used": m.tools_used}
        for m in messages
        if m.content and m.content.strip()
    ]




def _parse_tool_arguments(raw: str | None) -> tuple[dict, str | None]:
    """Parse a tool call's argument JSON, reporting (never raising) on garbage.

    A malformed arguments blob from the model used to 500 the whole request;
    it now becomes model-facing feedback so the call can be retried correctly.
    """
    text = raw or "{}"
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        return {}, f"invalid JSON: {exc.msg} at character {exc.pos}"
    if not isinstance(parsed, dict):
        return {}, f"expected a JSON object, got {type(parsed).__name__}"
    return parsed, None


def _tool_failure_message(name: str, exc: Exception) -> str:
    """What the model is told when a tool blows up — honest and actionable, no traceback."""
    if isinstance(exc, ValueError):
        # Registry-raised messages are already written for the model (unknown tool, missing args).
        return f"{name} rejected the call: {exc}"
    return (
        f"Tool {name} failed with {type(exc).__name__}: {exc}. "
        "Do not pretend it worked — retry once if it looks transient, otherwise tell the user "
        "which capability is unavailable."
    )


async def _save_message(
    profile_id: int,
    role: ChatRole,
    content: str,
    tool_name: str | None = None,
    tool_calls: list[dict] | None = None,
    *,
    reason: str | None = None,
    tools_used: list[str] | None = None,
) -> int | None:
    async with session_scope() as session:
        row = ChatMessage(
            profile_id=profile_id,
            role=role,
            content=content,
            tool_name=tool_name,
            tool_calls=tool_calls,
            reason=reason,
            tools_used=tools_used,
        )
        session.add(row)
        await session.commit()
        return row.id


@neatlogs.span(kind="WORKFLOW", name="agent_loop")
async def run_agent_loop(
    profile_id: int,
    user_message: str,
    on_step: Callable[[dict], Any] | None = None,
) -> AgentResult:
    with neatlogs.identify(session_id=str(profile_id), end_user_id=str(profile_id)):
        return await _run_agent_loop(profile_id, user_message, on_step)


async def _load_profile(profile_id: int) -> Profile | None:
    async with session_scope() as session:
        return await session.get(Profile, profile_id)


async def _run_agent_loop(
    profile_id: int,
    user_message: str,
    on_step: Callable[[dict], Any] | None = None,
) -> AgentResult:
    user_message_id = await _save_message(profile_id, ChatRole.USER, user_message)

    profile = await _load_profile(profile_id)
    handle = profile.handle if profile else ""
    name = profile.name if profile else ""
    tool_registry.set_current_profile_id(profile_id)

    try:
        result = await _agent_turn(
            profile_id, user_message, handle, name, on_step,
            user_message_id=user_message_id,
        )
    finally:
        tool_registry.set_current_profile_id(None)

    # Fire-and-forget: extract durable memories for memory.md + Chroma
    _schedule_memory_extraction(profile_id, user_message, result.content, handle=handle)
    return result


async def _agent_turn(
    profile_id: int,
    user_message: str,
    handle: str,
    name: str,
    on_step: Callable[[dict], Any] | None = None,
    user_message_id: int | None = None,
) -> AgentResult:
    t_turn = time.perf_counter()
    # Step 0: classify the turn (rules first; Jev stage 2 only when no rule
    # matched and its switch is on). classify_ms is part of the permanent
    # timing instrumentation (Step 0a / PROMPT 5 item 8).
    cls = await classify_turn(user_message)
    classify_ms = (time.perf_counter() - t_turn) * 1000
    allow = allowed_for(cls.final_class)
    history = await _load_history(profile_id)
    tool_calls_made: list[str] = []
    tool_executions: list[dict] = []

    # Resolve a pending MCP write from the previous turn BEFORE the model
    # speaks: a clear "yes" executes the tool and the note carries its REAL
    # outcome; anything else cancels it (never run without confirmation).
    resolution = await mcp_service.resolve_pending(profile_id, user_message)
    if resolution is not None and resolution.tool:
        tool_calls_made.append(resolution.tool)
        execution_info: dict = {
            "name": resolution.tool,
            "arguments": resolution.arguments,
            "sample_posts": [],
        }
        if isinstance(resolution.result, dict):
            execution_info["result"] = resolution.result
        tool_executions.append(execution_info)
        await _save_message(
            profile_id,
            ChatRole.TOOL,
            json.dumps(resolution.result),
            tool_name=resolution.tool,
            reason="user confirmed the pending write",
        )
        if on_step is not None:
            try:
                await on_step({
                    "type": "tool_start",
                    "tool": resolution.tool,
                    "arguments": resolution.arguments,
                    "reason": "user confirmed the pending write",
                })
                await on_step({"type": "tool_done", "tool": resolution.tool, "sample_posts": []})
            except Exception as exc:  # noqa: BLE001
                logger.warning("on_step failed for confirmed MCP tool: %s", exc)

    # Path decision (Phase D): fast = chitchat class AND no pending-write
    # resolution AND the message isn't coverage-guarded (a pending write or a
    # coverage-guarded recon ask forces the full path even for a chitchat
    # class). path_taken records the path ACTUALLY taken (may differ from
    # cls.path).
    fast_path = (
        cls.path == "fast"
        and resolution is None
        and not _coverage_required(user_message)
    )
    path_taken = "fast" if fast_path else "full"
    # reasoning_effort: free-tier classes answer with "low"; everything else
    # leaves the provider default (None = parameter not sent at all).
    effort = "low" if cls.final_class in _LOW_EFFORT_CLASSES else None

    messages: list[dict]
    tools: list[dict]
    if fast_path:
        # Fast path (chitchat): no MCP discovery, no profile/memory summary,
        # no tool specs — one completion against the trimmed prompt.
        messages = [
            {"role": "system", "content": build_fast_prompt(profile_id, handle, name)},
        ]
        mcp_ms = 0.0
        tools = []
    else:
        memory_summary = get_profile_summary(profile_id)
        messages = [
            {"role": "system", "content": build_system_prompt(profile_id, handle, name, memory_summary=memory_summary)},
        ]
        # MCP discovery runs in a background task (app/main.py lifespan ->
        # app.background.mcp_refresh); this turn only READS the cache, so it
        # never waits on the network (PROMPT 5 item 6). Cached specs merge
        # into the toolset below; an empty/stale cache just means the
        # connector's tools are absent this turn — the model reports that
        # honestly (prompt rule 16).
        mcp_ms = 0.0
        # Tier filter: only the tool costs/names this class allows are exposed.
        tools = tool_registry.list_tool_specs(allow.costs, allow.names)
    if resolution is not None:
        messages.append({"role": "system", "content": resolution.note})
    # TOOLS USED note (prompt rule 22): a separate system message BEFORE the
    # history, so history_start/user_idx math stays unchanged; the key itself
    # is stripped from the history dicts below so it never rides the payload.
    tools_note = _build_tools_note(history)
    if tools_note:
        messages.append({"role": "system", "content": tools_note})
    for msg in history:
        msg.pop("tools_used", None)
    messages.extend(history)
    # "Prompt build" phase = classification + history load + pending-write
    # resolution + (memory summary | fast prompt) + MCP discovery, all before
    # the model is ever called.
    prompt_ms = (time.perf_counter() - t_turn) * 1000

    # Fit boundaries for the token budget (_fit_messages): leading system
    # prompt(s) are protected; the droppable region is older history; the
    # newest history entry is the current user message and is protected. The
    # fit re-runs before every completion because tool results grow the
    # transcript mid-turn.
    history_start = len(messages) - len(history)
    user_idx = len(messages) - 1 if history else history_start

    force_final = False
    greeting_only = is_greeting_only(user_message)
    # Evidence-gate state (L10): per-handle coverage of the handles the USER
    # named, computed from this turn's check_niche_trends results only.
    coverage_active = not greeting_only and _coverage_required(user_message)
    coverage: dict[str, str] = {h: "not_run" for h in _extract_named_handles(user_message)}
    peers_discovered = False
    frameworks_seen: dict | None = None
    # One corrective nudge per turn: "coverage" (named handles never scanned)
    # or "claim" (fabricated action with zero tools) — never both.
    nudge_state: str | None = None
    completion_ms: list[float] = []
    models_seen: list[str] = []
    prompt_tokens = 0
    completion_tokens = 0
    reasoning_tokens = 0
    tool_ms = 0.0
    jev.reset_turn_timing()

    def _log_turn() -> None:
        logger.info(
            "turn metrics: total=%.0fms prompt=%.0fms mcp=%.0fms completions=[%s]ms "
            "tools=%.0fms jev=%.0fms greeting_only=%s model=%s tokens=%d/%d reasoning=%d",
            (time.perf_counter() - t_turn) * 1000,
            prompt_ms,
            mcp_ms,
            " ".join(f"{ms:.0f}" for ms in completion_ms),
            tool_ms,
            jev.turn_timing_ms(),
            greeting_only,
            ",".join(models_seen) or "?",
            prompt_tokens,
            completion_tokens,
            reasoning_tokens,
        )

    def _finish(taken: str, content: str) -> AgentResult:
        """Log the turn, schedule its classification row, build the result.

        The row write is fire-and-forget: a failure can never affect the reply.
        Missing metrics stay OUT of `timings` (absent key = NULL, never 0);
        credits_spent has no meter yet and is explicitly NULL.
        """
        _log_turn()
        total_ms = (time.perf_counter() - t_turn) * 1000
        timings: dict = {
            "classify_ms": round(classify_ms, 1),
            "prompt_ms": round(prompt_ms, 1),
            "total_ms": round(total_ms, 1),
            "completion_ms": round(sum(completion_ms), 1),
        }
        if mcp_ms > 0:
            timings["mcp_ms"] = round(mcp_ms, 1)
        if tool_ms > 0:
            timings["tool_ms"] = round(tool_ms, 1)
        jev_ms = jev.turn_timing_ms()
        if jev_ms > 0:
            timings["jev_ms"] = round(jev_ms, 1)
        if models_seen:
            timings["model"] = ",".join(models_seen)
        if prompt_tokens:
            timings["prompt_tokens"] = prompt_tokens
        if completion_tokens:
            timings["completion_tokens"] = completion_tokens
        if reasoning_tokens:
            timings["reasoning_tokens"] = reasoning_tokens
        _schedule_classification(
            TurnClassification(
                profile_id=profile_id,
                message_id=user_message_id,
                message_text_hash=log_hash(user_message),
                message_preview=log_preview(user_message),
                rule_class=cls.rule_class,
                rule_matched=cls.rule_matched,
                jev_called=cls.jev_called,
                jev_class=cls.jev_class,
                jev_probs=cls.jev_probs,
                jev_confidence=cls.jev_confidence,
                jev_latency_ms=cls.jev_latency_ms,
                jev_error=cls.jev_error,
                final_class=cls.final_class,
                path_taken=taken,
                tools_called=list(tool_calls_made),
                credits_spent=None,
                total_latency_ms=int(total_ms),
                user_corrected=None,
                timings=timings,
            )
        )
        return AgentResult(
            content=content,
            tool_calls_made=list(tool_calls_made),
            tool_executions=list(tool_executions),
            path_taken=taken,
            classification_id=None,
        )

    for _ in range(MAX_TOOL_ITERATIONS):
        if (
            not force_final
            and not greeting_only
            and len(tool_calls_made) >= SUFFICIENCY_MIN_TOOLS
            and await _enough_information(user_message, messages)
        ):
            logger.info(
                "jev early-exit: information sufficient after %d tool calls, forcing final answer",
                len(tool_calls_made),
            )
            force_final = True
        use_tools = [] if (force_final or greeting_only) else tools
        tools_tokens = _estimate_tokens(json.dumps(use_tools)) if use_tools else 0
        user_idx = _fit_messages(messages, history_start, user_idx, tools_tokens)
        started = time.perf_counter()
        completion = await chat_completion_with_fallback(messages, use_tools, effort=effort)
        completion_ms.append((time.perf_counter() - started) * 1000)
        choice = completion.choices[0].message
        model = getattr(completion, "model", None)
        if model and model not in models_seen:
            models_seen.append(model)
        usage = getattr(completion, "usage", None)
        if usage is not None:
            prompt_tokens += int(getattr(usage, "prompt_tokens", 0) or 0)
            completion_tokens += int(getattr(usage, "completion_tokens", 0) or 0)
            details = getattr(usage, "completion_tokens_details", None)
            reasoning = getattr(details, "reasoning_tokens", None) if details else None
            if reasoning:
                reasoning_tokens += int(reasoning)

        if not choice.tool_calls:
            reply = choice.content or ""
            # finish_reason lives on the CHOICE, not the message.
            finish_reason = getattr(completion.choices[0], "finish_reason", None)
            not_run = [h for h, s in coverage.items() if s == "not_run"]
            incomplete = [h for h, s in coverage.items() if not s.startswith("scanned")]
            if not greeting_only and nudge_state is None:
                if _should_nudge(user_message, reply, bool(tool_calls_made)):
                    # Fabricated action claim (or an un-acted search command): nudge
                    # once and give the model a real chance to call the tool before
                    # letting a tool-less reply through.
                    logger.info("claim gate: reply claims action with zero tools, nudging model")
                    messages.append({"role": "assistant", "content": reply})
                    messages.append({"role": "user", "content": _NO_TOOL_NUDGE})
                    nudge_state = "claim"
                    continue
                if coverage_active and not_run and not _DECLINE_RE.search(reply):
                    # Evidence gate (L10): the user named handles that this turn's
                    # tool results never covered. One nudge to run the missing
                    # scans — this fires even when OTHER tools ran, so
                    # "some tool ran" can no longer satisfy the gate.
                    logger.info(
                        "coverage gate: %s not scanned, nudging model",
                        ", ".join(f"@{h}" for h in not_run),
                    )
                    messages.append({"role": "assistant", "content": reply})
                    messages.append(
                        {
                            "role": "user",
                            "content": _COVERAGE_NUDGE.format(
                                handles=", ".join(f"@{h}" for h in not_run)
                            ),
                        }
                    )
                    nudge_state = "coverage"
                    continue
            if (
                nudge_state == "claim"
                and not tool_calls_made
                and _should_nudge(user_message, reply, False)
            ):
                logger.warning("claim gate: model still claims action with zero tools, appending disclaimer")
                reply += _HONESTY_DISCLAIMER
            if (
                coverage_active
                and incomplete
                and not (_DECLINE_RE.search(reply) and not tool_calls_made)
            ):
                # Coverage still incomplete (failed or never-run handles): the
                # reply must OPEN with the coverage block and may not claim a
                # "full picture" — strip overclaims either way. A zero-tool
                # honest decline passes untouched (the decline IS the disclosure).
                reply = _FULL_PICTURE_RE.sub("partial picture", reply)
                if "coverage" not in reply[:400].lower():
                    reply = _coverage_block(coverage, peers_discovered, frameworks_seen) + "\n" + reply
            if finish_reason == "length":
                started = time.perf_counter()
                reply = await _continue_truncated(messages, reply)
                completion_ms.append((time.perf_counter() - started) * 1000)
            # tools_used rides the FINAL reply row only (the row the next
            # turn's TOOLS USED note is derived from); the mid-loop
            # tool-calling row below stays bare.
            await _save_message(
                profile_id,
                ChatRole.ASSISTANT,
                reply,
                tools_used=(tool_calls_made or None),
            )
            return _finish(path_taken, reply)

        messages.append({"role": "assistant", "content": choice.content, "tool_calls": choice.tool_calls})

        serialized_tool_calls = [
            {"id": call.id, "type": call.type, "function": {"name": call.function.name, "arguments": call.function.arguments}}
            for call in choice.tool_calls
        ]
        await _save_message(
            profile_id, ChatRole.ASSISTANT, choice.content or "", tool_calls=serialized_tool_calls
        )

        for call in choice.tool_calls:
            arguments, parse_error = _parse_tool_arguments(call.function.arguments)
            if parse_error:
                logger.warning("tool %s received malformed arguments: %s", call.function.name, parse_error)

            if on_step is not None:
                try:
                    await on_step({
                        "type": "tool_start",
                        "tool": call.function.name,
                        "arguments": arguments,
                        "reason": arguments.get("reason"),
                    })
                except Exception as exc:  # noqa: BLE001
                    logger.warning("on_step tool_start failed: %s", exc)

            if parse_error:
                result = {
                    "error": (
                        f"Arguments for {call.function.name} were not valid JSON object text "
                        f"({parse_error}). Call the tool again with well-formed JSON."
                    )
                }
            else:
                started = time.perf_counter()
                try:
                    result = await asyncio.wait_for(
                        tool_registry.call_tool(call.function.name, arguments),
                        timeout=TOOL_TIMEOUT_SECONDS,
                    )
                except TimeoutError:
                    # A hung external call must degrade to an honest, visible
                    # failure — never a silently dead turn.
                    logger.error(
                        "tool %s timed out after %ds", call.function.name, TOOL_TIMEOUT_SECONDS
                    )
                    result = {
                        "error": (
                            f"Tool {call.function.name} timed out after {TOOL_TIMEOUT_SECONDS}s "
                            "(external service too slow or unreachable). Do not claim it worked: "
                            "retry once or tell the user which capability failed."
                        )
                    }
                except Exception as exc:
                    # One failing tool must never abort the turn: the model is told what
                    # broke and can retry or report the gap honestly.
                    logger.exception("tool %s raised %s", call.function.name, type(exc).__name__)
                    result = {"error": _tool_failure_message(call.function.name, exc)}
                tool_ms += (time.perf_counter() - started) * 1000
            result_text = json.dumps(result)

            tool_calls_made.append(call.function.name)

            # Evidence gate bookkeeping (L10): fold this turn's scan outcomes
            # into per-handle coverage; remember peer-discovery and framework
            # provenance for the coverage block.
            if coverage_active and isinstance(result, dict):
                if call.function.name == "check_niche_trends":
                    _record_scan_coverage(coverage, arguments, result)
                elif call.function.name == "discover_and_extract_niche_frameworks":
                    peers_discovered = True
                elif call.function.name == "get_peer_advice":
                    frameworks_seen = {
                        key: result.get(key)
                        for key in ("found", "niche_title", "source_handles", "age_days")
                    }

            # Extract sample discovered posts (up to 4) if tool returned viral posts or matches
            sample_posts = []
            if isinstance(result, dict):
                candidates = result.get("viral_posts") or result.get("posts") or []
                for p in candidates[:4]:
                    sample_posts.append({
                        "author": p.get("author") or p.get("author_handle") or p.get("authorUsername"),
                        "text": (p.get("caption") or p.get("text") or "")[:120],
                        "likes": p.get("likes") or p.get("likeCount"),
                        "url": p.get("url") or p.get("platform_url"),
                    })

            execution_info = {
                "name": call.function.name,
                "arguments": arguments,
                "sample_posts": sample_posts,
            }
            # Ship the raw result for analytics so the UI can render the chart
            # from the exact numbers the agent saw. Gated to keep payloads small.
            if call.function.name == "get_analytics" and isinstance(result, dict):
                execution_info["result"] = result
            tool_executions.append(execution_info)

            if on_step is not None:
                try:
                    await on_step({
                        "type": "tool_done",
                        "tool": call.function.name,
                        "sample_posts": sample_posts,
                    })
                except Exception as exc:  # noqa: BLE001
                    logger.warning("on_step tool_done failed: %s", exc)


            await _save_message(
                profile_id,
                ChatRole.TOOL,
                result_text,
                tool_name=call.function.name,
                reason=arguments.get("reason"),
            )
            context_text = json.dumps(_slim_for_context(call.function.name, result))
            if len(context_text) > TOOL_CONTEXT_CHAR_LIMIT:
                context_text = context_text[:TOOL_CONTEXT_CHAR_LIMIT] + " ...[truncated]"
            messages.append({"role": "tool", "tool_call_id": call.id, "content": context_text})


    fallback_reply = "I ran into trouble completing that — could you try rephrasing?"
    await _save_message(
        profile_id,
        ChatRole.ASSISTANT,
        fallback_reply,
        tools_used=(tool_calls_made or None),
    )
    return _finish(path_taken, fallback_reply)

