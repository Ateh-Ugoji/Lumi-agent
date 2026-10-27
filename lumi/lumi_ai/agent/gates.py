"""Gates that keep the agent honest: no claimed work without tools, no plan for accounts never scanned.

Ported unchanged in behaviour from ``lumi/legacy/app/agent/loop.py`` (action-claim gate, L10 coverage gate).
Everything here is pure: no I/O, no model calls.
"""

from __future__ import annotations

import re
from typing import Any

# --- action-claim gate ------------------------------------------------------
# A model turn that claims work was done/running (or promises to do it next)
# while having called ZERO tools is fabrication. One corrective nudge is
# injected; if the model still claims without acting, an honest disclaimer is
# appended to the reply the user sees.
COMPLETED_ACTION_PATTERNS = (
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
PROMISE_ACTION_PATTERNS = (
    r"\bi'?ll (run|do a|do the|start|kick off|launch)\b[^\n]{0,60}\b(recon|scan|search|analysis)\b",
    r"\bi'?ll (run|scan|search)\b[^\n]{0,40}\b(through|for|on)\b",
    r"\blet me (run|scan|search|dig)\b",
)
ACTION_CLAIM_RE = re.compile(
    "|".join(f"(?:{p})" for p in COMPLETED_ACTION_PATTERNS + PROMISE_ACTION_PATTERNS),
    re.IGNORECASE,
)
# The USER's message explicitly demanding a data-fetch action. Reply-wording
# patterns are evasive (the model keeps inventing phrasings like "Good, fresh
# numbers now"), so the user side of the conversation gates too: a command to
# search/scan + zero tools = fabrication unless the reply honestly declines.
ACTION_REQUEST_RE = re.compile(
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
BARE_HANDLES_RE = re.compile(r"^\s*(?:@[A-Za-z0-9_]{1,15}[.,]?\s*[,&]?\s*)+$")
# Tier-2 reply phrasing: presenting fresh data without a concrete past-action
# claim ("Here's what's working right now for @beaconsai" with zero tools).
PRESENTING_RE = re.compile(
    r"\bhere'?s what(?:'s| is)? (?:working|happening|trending)\b",
    re.IGNORECASE,
)
# Honest markers (no nudge, no disclaimer): replies that admit they cannot do
# the work, OR that explicitly label their content as stored/standing data
# (prompt rule 15's compliant framing of get_peer_advice results).
DECLINE_RE = re.compile(
    r"\b(?:can'?t|cannot|couldn'?t|unable|not able|don'?t have|do not have"
    r"|no access|haven'?t|didn'?t run|not actually run|timed out|failed"
    r"|blocked|doesn'?t work|does not work"
    # connector not connected is an honest decline too ("Google isn't connected")
    r"|not (?:yet )?connected|isn'?t connected|is not connected|connect (?:it |google |them )?first"
    r"|(?:stored|standing) (?:advice|recon|analysis|picture|data|patterns))\b",
    re.IGNORECASE,
)
NO_TOOL_NUDGE = (
    "System reminder for this turn only: you have not called any tool yet. Do not describe "
    "work as done, running, or found unless a tool actually produced it this turn. If the "
    "user's request needs data, call the needed tool(s) NOW and answer from their results. "
    "If you genuinely cannot do it, say plainly what you cannot do and why."
)
HONESTY_DISCLAIMER = (
    "\n\nCorrection: I have not actually run any scan, recon, or search for this message, "
    "so any claims above about finished or running work are unverified."
)

# --- coverage evidence gate (prompt rules 17/18 — the Beacons failure, L10) ---
# Only @-tagged tokens count as user-named handles (rule-13 normalization: strip
# @, lowercase, unique) — a bare noun is not a handle.
HANDLE_TAG_RE = re.compile(r"(?<![\w@])@([A-Za-z0-9_]{1,15})\b")
# A deliverable ask (plan/strategy/analysis/…) or a peer-discovery ask. Combined
# with a named handle these make the turn a recon request the evidence gate covers.
DELIVERABLE_RE = re.compile(
    r"\b(?:plan|strategy|analysis|comparison|breakdown|outline|calendar|schedule|audit|report)\b"
    r"|(?:find|discover|who are|list)\b[^\n]{0,40}\bpeers?\b",
    re.IGNORECASE,
)
# "full picture" family — stripped from any reply whose coverage is incomplete.
FULL_PICTURE_RE = re.compile(
    r"\b(?:full|complete|entire|whole)\s+picture\b", re.IGNORECASE
)

COVERAGE_NUDGE = (
    "System reminder for this turn only: you have NOT yet scanned these handles the user named: "
    "{handles}. Call check_niche_trends with exactly those handles NOW, then answer beginning with "
    "the coverage line (rule 17: scanned (n posts) / failed (why) / not run, one per handle). Never "
    "present a plan or findings for a handle you have not scanned."
)


def extract_named_handles(user_message: str) -> list[str]:
    """@-tagged handles from the user's message, normalized and de-duplicated."""
    return list(
        dict.fromkeys(m.lower() for m in HANDLE_TAG_RE.findall(user_message or ""))
    )


def coverage_required(user_message: str) -> bool:
    """L10 trigger: names at least one handle AND asks for a scan or a deliverable."""
    if not extract_named_handles(user_message):
        return False
    text = user_message or ""
    return bool(ACTION_REQUEST_RE.search(text) or DELIVERABLE_RE.search(text))


def record_scan_coverage(
    coverage: dict[str, str], arguments: dict, result: Any
) -> None:
    """Fold one check_niche_trends call's outcome into per-handle coverage.

    coverage values: "scanned (n posts)" | "failed (why)" | "not_run". Only
    handles the USER named are tracked — scans of other handles are ignored.
    """
    requested = [
        str(h).lstrip("@").lower() for h in (arguments or {}).get("handles") or []
    ]
    failed: dict[str, str] = {}
    for entry in (result or {}).get("failed_handles") or []:
        handle, sep, reason = str(entry).partition(":")
        if sep:
            failed[handle.strip().lstrip("@").lower()] = (
                reason.strip() or "lookup failed"
            )
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


def coverage_block(
    coverage: dict[str, str], peers_discovered: bool, frameworks: dict | None
) -> str:
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
        parts.append(
            line
            + (
                ", covers the named accounts"
                if overlap
                else ", different accounts than named"
            )
        )
    else:
        parts.append("frameworks used: none this turn")
    return "Recon coverage: " + " | ".join(parts)


def claims_action_without_tools(reply: str, tools_ran: bool) -> bool:
    """True when the reply claims/promises scan-style work but no tool ran this turn."""
    if tools_ran:
        return False
    return bool(ACTION_CLAIM_RE.search(reply or ""))


def should_nudge(user_message: str, reply: str, tools_ran: bool) -> bool:
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
    if ACTION_CLAIM_RE.search(text):
        return True
    if DECLINE_RE.search(text):
        return False
    if PRESENTING_RE.search(text):
        return True
    if ACTION_REQUEST_RE.search(user_message or ""):
        return True
    return bool(BARE_HANDLES_RE.match(user_message or ""))
