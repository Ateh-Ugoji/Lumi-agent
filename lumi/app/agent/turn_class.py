"""Turn classifier (L13 item 1 / PROMPT 5 item 1): rules first, Jev second.

Rules run synchronously at zero latency. When they produce a confident class
the turn is classified without any LLM call. Only when NO rule matched does
the optional Jev stage run — and only when its kill-switch
(``TURN_CLASS_JEV_ENABLED``, default off per spec) is on. Jev unreachable,
timed out (``TURN_CLASS_JEV_TIMEOUT_MS``), or scoring below
``TURN_CLASS_JEV_HIGH``/``TURN_CLASS_JEV_LOW`` all land on ``other`` (full
path, all tools) — a classifier failure can only ever widen access, never
narrow it.

The 4-question Jev schema is fixed: four Noul scores in 0..1 (history_meta,
read_cheap, live_scan, write); ``jev_confidence`` is the max score and the
adopted class the argmax when it clears the high threshold. ``chitchat`` and
``memory`` are deliberately rule-only (a whitelist greeting and a
"remember..." opener respectively never need a model to detect).

Also home of the greeting whitelist (moved here from loop.py so the
classifier and the greeting gate cannot drift; loop re-exports
``is_greeting_only``).
"""

import asyncio
import hashlib
import re
import time
from dataclasses import dataclass
from typing import Any

from app.config import get_settings
from app.services import jev

# --- the seven classes (L13 item 1 table) -----------------------------------

CHITCHAT = "chitchat"
HISTORY_META = "history_meta"
MEMORY = "memory"
READ_CHEAP = "read_cheap"
LIVE_SCAN = "live_scan"
WRITE = "write"
OTHER = "other"

TURN_CLASSES = (
    CHITCHAT,
    HISTORY_META,
    MEMORY,
    READ_CHEAP,
    LIVE_SCAN,
    WRITE,
    OTHER,
)

# --- tools allowed per class -------------------------------------------------
# costs: which cost tiers (registry ToolSpec.cost) this class may see.
# names: optional exact-name allowlist that further restricts to those tools
#        (memory = remember/recall_memory only — never other free tools).
# chitchat/history_meta allow NOTHING (fast path / answer from the tool log);
# ambiguous turns land on OTHER = every tier (tool_choice=auto, full path).


@dataclass(frozen=True)
class AllowedTools:
    costs: frozenset[str]
    names: frozenset[str] | None = None


CLASS_ALLOWED: dict[str, AllowedTools] = {
    CHITCHAT: AllowedTools(frozenset()),
    HISTORY_META: AllowedTools(frozenset()),
    MEMORY: AllowedTools(frozenset({"free"}), frozenset({"remember", "recall_memory"})),
    READ_CHEAP: AllowedTools(frozenset({"free"})),
    LIVE_SCAN: AllowedTools(frozenset({"free", "credits", "llm"})),
    WRITE: AllowedTools(frozenset({"free", "write"})),
    OTHER: AllowedTools(frozenset({"free", "credits", "llm", "write"})),
}

# Classes Jev may act on in the 0.6-0.85 confidence band. A middling guess may
# only ever select a free-tier path; live_scan/write need >= 0.85 (L13 item 8).
FREE_TIER_CLASSES = frozenset({CHITCHAT, HISTORY_META, MEMORY, READ_CHEAP})


def allowed_for(turn_class: str) -> AllowedTools:
    """Tier/name allowlist for a class; unknown classes get the full path."""
    return CLASS_ALLOWED.get(turn_class, CLASS_ALLOWED[OTHER])


# --- greeting whitelist (moved from loop.py; loop re-exports) ---------------
# Whitelist of greeting-only phrases. Matches run with NO tools (no
# recall_memory, no get_peer_advice, ...) so a plain "hi" is answered by the
# normal model in one completion instead of being treated as a task.
_GREETING_PHRASES = frozenset({
    "hi", "hey", "hello", "yo", "hiya", "howdy", "sup", "gm", "gn",
    "hi there", "hey there", "hello there", "hey you",
    "how are you", "how r u", "how ru", "how are you doing",
    "how's it going", "hows it going", "what's up", "whats up", "wassup",
    "you there", "you online", "are you there", "are you online",
    "good morning", "good afternoon", "good evening", "good night",
    "thanks", "thank you", "thx", "ty", "thanks a lot", "thank you so much",
    "bye", "goodbye", "see you", "see ya", "talk later",
    "ok", "okay", "cool", "nice", "great", "awesome", "perfect", "love it",
    "wow", "lol", "haha", "lmao", "yay", "test", "ping",
})


def is_greeting_only(message: str) -> bool:
    """True for short pleasantry-only messages (whitelist; anything else is a task)."""
    text = (message or "").strip().lower()
    if not text or len(text) > 64:
        return False
    tokens = re.sub(r"[^\w\s']+", " ", text).split()
    if not tokens or len(tokens) > 8:
        return False
    return " ".join(tokens) in _GREETING_PHRASES


# --- rules -------------------------------------------------------------------
# One entry = (rule name, tuple of alternative regexes, class). A message is
# scored against EVERY rule: all matches agreeing on one class wins; matches
# that disagree are ambiguous -> "other" (full path); no match at all -> "other"
# and, if enabled, the Jev stage. Regexes run over a lowercased message.


@dataclass(frozen=True)
class Rule:
    name: str
    patterns: tuple[str, ...]
    cls: str


_RULES: tuple[Rule, ...] = (
    # history_meta — "what tools did you use", "list them", "what did you do"
    Rule(
        "history_tools_what",
        (r"\b(?:what|which)\b[^?]{0,60}\btools?\b",),
        HISTORY_META,
    ),
    Rule(
        "history_tools_list",
        (r"\b(?:list|show|name|call|repeat|re-?run)\b[^?]{0,50}\btools?\b",),
        HISTORY_META,
    ),
    Rule(
        "history_tools_used",
        (r"\btools?\b[^?]{0,50}\b(?:use|used|call|called|ran|run|before|earlier)\b",),
        HISTORY_META,
    ),
    Rule(
        "history_tools_log",
        (r"\b(?:tool|tools)\s+(?:log|history|calls?)\b",),
        HISTORY_META,
    ),
    Rule(
        "history_list_them",
        (r"^\s*(?:can you\s+|please\s+|pls\s+)?list\s+(?:them|those|it all|everything)\b",),
        HISTORY_META,
    ),
    Rule(
        "history_what_did_you",
        (
            r"\bwhat\s+(?:did|do)\s+you\s+(?:just\s+)?(?:do|run|call|execute)\b",
            r"\bwhat\s+(?:have|had)\s+you\s+(?:done|run|called)\b",
            r"\b(?:what|which)\s+(?:steps?|actions?)\s+did\s+you\s+take\b",
        ),
        HISTORY_META,
    ),
    # memory — "remember ...", "what do you know about me"
    Rule(
        "memory_remember",
        (r"^\s*(?:please\s+|pls\s+)?remember\b(?!\s+to\b)",),
        MEMORY,
    ),
    Rule(
        "memory_query",
        (
            r"\bwhat\s+do\s+you\s+(?:know|remember)\b",
            r"\bwhat\s+(?:have|had)\s+you\s+(?:saved|stored|noted|recorded)\b",
            r"\byour\s+(?:memory|memories|notes)\b",
        ),
        MEMORY,
    ),
    Rule(
        "memory_save",
        (r"^\s*(?:please\s+|pls\s+)?(?:save|store|note|keep)\s+(?:this|that)\b",),
        MEMORY,
    ),
    # read_cheap — the user's OWN data: posts, voice, analytics (DB/Chroma)
    Rule(
        "read_own_data",
        (
            (
                r"\bmy\s+(?:own\s+)?(?:posts?|tweets?|voice|analytics|metrics|"
                r"stats|numbers|profile|replies|activity|content|style|followers)\b"
            ),
        ),
        READ_CHEAP,
    ),
    Rule(
        "read_own_history",
        (
            r"\bwhat\s+have\s+i\s+(?:posted|tweeted|written)\b",
            r"\b(?:show|get|pull|give|fetch)\s+me\s+my\b",
            r"\bhow\s+(?:am\s+i\s+doing|are\s+my\s+posts\s+doing)\b",
        ),
        READ_CHEAP,
    ),
    # live_scan — explicit scan intent or a named @handle (rule 13: a bare
    # tag IS a lookup request; the claim gate's _BARE_HANDLES_RE agrees)
    Rule(
        "scan_verb",
        (
            (
                r"\b(?:scan|search|look\s*up|lookup|recon(?:naissance)?|"
                r"scout|research|dig\s+into)\b"
            ),
        ),
        LIVE_SCAN,
    ),
    Rule(
        "scan_external_fetch",
        (r"\b(?:find|fetch|pull)\b[^?]{0,40}\b(?:posts?|tweets?|results?|data)\b",),
        LIVE_SCAN,
    ),
    Rule(
        "scan_trending",
        (
            (
                r"\b(?:check|check\s+out)\b[^?]{0,40}\b(?:trends?|trending|viral|"
                r"niche|competitors?|twitter)\b"
            ),
            r"\bwhat(?:'s| is| are)\s+trending\b",
        ),
        LIVE_SCAN,
    ),
    Rule("scan_named_handle", (r"@[a-z0-9_]{1,15}",), LIVE_SCAN),
    # write — create/submit/connect: goes through the confirmation machine (L6)
    Rule(
        "write_doc",
        (
            (
                r"\b(?:create|make|write|draft|compose|generate|build)\b[^?]{0,40}"
                r"\b(?:doc|document|file|note|sheet|page)\b"
            ),
            (
                r"\b(?:append|add)\b[^?]{0,30}\b(?:to|into)\b[^?]{0,25}"
                r"\b(?:doc|drive|file|folder)\b"
            ),
        ),
        WRITE,
    ),
    Rule(
        "write_submit",
        (
            (
                r"\bsubmit\b[^?]{0,40}\b(?:action|suggestion|attempt|edit|rewrite|"
                r"changes?)\b"
            ),
            (
                r"\b(?:accept|reject|approve|decline)\b[^?]{0,30}\b(?:suggestion|"
                r"action|attempt|rewrite|edit)\b"
            ),
        ),
        WRITE,
    ),
    Rule(
        "write_connect",
        (r"\b(?:connect|link|authori[sz]e)\b[^?]{0,40}\b(?:account|twitter|\bx\b)\b",),
        WRITE,
    ),
)

_COMPILED: tuple[tuple[str, tuple[re.Pattern[str], ...], str], ...] = tuple(
    (rule.name, tuple(re.compile(p) for p in rule.patterns), rule.cls)
    for rule in _RULES
)


@dataclass
class Classification:
    rule_class: str
    rule_matched: str | None  # "+".join(names); None when nothing matched
    final_class: str
    path: str  # "fast" (chitchat) | "full"
    ambiguous: bool = False  # rules matched but disagreed -> treated as other
    jev_called: bool = False
    jev_class: str | None = None
    jev_probs: list[dict[str, Any]] | None = None
    jev_confidence: float | None = None
    jev_latency_ms: int | None = None
    jev_error: str | None = None

    @property
    def matched_rules(self) -> list[str]:
        return self.rule_matched.split("+") if self.rule_matched else []


def _path_for(turn_class: str) -> str:
    return "fast" if turn_class == CHITCHAT else "full"


def classify(message: str) -> Classification:
    """Rules-only classification. Never calls a model (zero latency)."""
    text = (message or "").strip().lower()
    hits: list[tuple[str, str]] = []
    if is_greeting_only(text):
        hits.append(("greeting", CHITCHAT))
    for name, patterns, cls in _COMPILED:
        if any(p.search(text) for p in patterns):
            hits.append((name, cls))

    if not hits:
        return Classification(
            rule_class=OTHER,
            rule_matched=None,
            final_class=OTHER,
            path=_path_for(OTHER),
        )

    names = "+".join(name for name, _ in hits)
    classes = {cls for _, cls in hits}
    if len(classes) == 1:
        turn_class = hits[0][1]
        return Classification(
            rule_class=turn_class,
            rule_matched=names,
            final_class=turn_class,
            path=_path_for(turn_class),
        )
    # Ambiguous: rules matched but disagreed -> "other" (spec: ambiguous means
    # other). rule_matched keeps every hit so scripts can find the conflict.
    return Classification(
        rule_class=OTHER,
        rule_matched=names,
        final_class=OTHER,
        path=_path_for(OTHER),
        ambiguous=True,
    )


# --- stage 2: Jev (off by default) -------------------------------------------

_JEV_QUESTIONS = {
    "history_meta": (
        "Is the person asking what the assistant just did, which tools ran, "
        "or what happened earlier in this conversation?"
    ),
    "read_cheap": (
        "Is the person asking about their OWN stored data — their posts, "
        "voice/profile, analytics or stats — rather than the wider web?"
    ),
    "live_scan": (
        "Does the person want a fresh search or scan of outside sources — "
        "trending posts, named accounts, or anything that must be looked up live?"
    ),
    "write": (
        "Does the person want a document/file created or submitted, an action "
        "confirmed, or an account connected?"
    ),
}


async def _jev_stage(text: str) -> Classification:
    """Stage 2: fixed 4-question Noul schema over the unmatched message."""
    settings = get_settings()
    started = time.perf_counter()
    error: str | None = None
    scores: dict[str, float] | None = None
    try:
        scores = await asyncio.wait_for(
            jev.ask_noul({"message": text}, _JEV_QUESTIONS),
            timeout=settings.turn_class_jev_timeout_ms / 1000,
        )
    except TimeoutError:
        error = "timeout"
    latency_ms = int((time.perf_counter() - started) * 1000)

    probs: list[dict[str, Any]] | None = None
    confidence: float | None = None
    jev_class: str | None = None
    final_class = OTHER

    if scores is None:
        error = error or "unavailable"
    else:
        probs = [{"name": name, "score": score} for name, score in scores.items()]
        if scores:
            jev_class = max(scores, key=scores.__getitem__)
            confidence = scores[jev_class]
            # L13 item 8 banding: >= high -> act on any class; low..high -> act
            # only for free-tier classes (a middling guess must never start a
            # credits/write path); < low -> "other".
            if confidence >= settings.turn_class_jev_high or (
                confidence >= settings.turn_class_jev_low
                and jev_class in FREE_TIER_CLASSES
            ):
                final_class = jev_class

    return Classification(
        rule_class=OTHER,
        rule_matched=None,
        final_class=final_class,
        path=_path_for(final_class),
        jev_called=True,
        jev_class=jev_class,
        jev_probs=probs,
        jev_confidence=confidence,
        jev_latency_ms=latency_ms,
        jev_error=error,
    )


async def classify_turn(message: str) -> Classification:
    """Full classification: rules first, Jev stage 2 only when no rule matched.

    The Jev stage runs only if its kill-switch (TURN_CLASS_JEV_ENABLED) is on;
    a rules match — including an ambiguous one — never waits on a model.
    """
    result = classify(message)
    if result.rule_matched is not None:
        return result
    if not get_settings().turn_class_jev_enabled:
        return result
    return await _jev_stage((message or "").strip().lower())


# --- log helpers (L13 item 9 columns) ---------------------------------------


def log_preview(message: str, limit: int = 120) -> str:
    """First ~120 chars of the message, whitespace-collapsed for the log row."""
    return " ".join((message or "").split())[:limit]


def log_hash(message: str) -> str:
    """Stable hash of the normalized message (dup detection in the report)."""
    normalized = " ".join((message or "").lower().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:32]
