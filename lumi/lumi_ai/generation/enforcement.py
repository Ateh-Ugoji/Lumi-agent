"""Deterministic checks of a draft plus the 'does it still mean the same' judge.

``must_keep_passed`` is false for any hard failure: over the platform's length, a required
phrase missing, a link or @mention of the source lost, or more hashtags than the platform
accepts. Only a draft that passes those is shown to the judge, as the legacy flow did.
"""

from __future__ import annotations

import re

from lumi_ai.config import AIConfig
from lumi_ai.generation.difficulty import protected_tokens
from lumi_ai.generation.platforms import measure, rules_for
from lumi_ai.generation.types import GenerationBrief, Review
from lumi_ai.ports import SemanticJudge

_HASHTAG = re.compile(r"(?<![\w/&#])#\w+")
UNAVAILABLE = "judge unavailable — flagged for manual review"
_MEANING = (
    "Does the rewrite preserve the original caption's meaning, claims, and intent, "
    "even though the wording and voice may differ?"
)


def hashtags(text: str) -> list[str]:
    return _HASHTAG.findall(text)


def deterministic_failures(brief: GenerationBrief, text: str) -> list[str]:
    """Why ``text`` breaks a hard rule of the platform or the request. Empty means it passes."""
    rules = rules_for(brief.platform)
    failures: list[str] = []
    length = measure(brief.platform, text)
    if length > rules.hard_limit:
        failures.append(
            f"{length} characters exceeds the {rules.hard_limit} character limit of {rules.label}"
        )
    lowered = text.lower()
    missing = [p for p in brief.must_keep if p.lower() not in lowered]
    if missing:
        failures.append(f"missing required phrase(s): {', '.join(missing)}")
    if brief.mode == "repurpose" and brief.source_text:
        lost = [
            t
            for t in dict.fromkeys(protected_tokens(brief.source_text))
            if t.lower() not in lowered
        ]
        if lost:
            failures.append(
                f"lost link(s) or @mention(s) of the source: {', '.join(lost)}"
            )
    if rules.hashtag_cap_enforced:
        found = len(hashtags(text))
        if found > rules.hashtags_max:
            failures.append(
                f"{found} hashtags; {rules.label} accepts at most {rules.hashtags_max}"
            )
    return failures


class EnforcementReviewer:
    """Deterministic checks, then (repurpose mode only) the judge's ``preserves_meaning``.

    A topic post has no source to stay faithful to, so no meaning judge runs for it.
    """

    def __init__(
        self, judge: SemanticJudge | None, config: AIConfig | None = None
    ) -> None:
        self._judge = judge
        self._min_confidence = (config or AIConfig()).generation_judge_confidence

    async def review(self, brief: GenerationBrief, text: str) -> Review:
        failures = deterministic_failures(brief, text)
        if failures:
            note = "; ".join(failures)
            return Review(
                must_keep_passed=False,
                failures=tuple(failures),
                feedback=note,
                needs_retry=True,
                revision_note=f"Previous attempt failed enforcement: {note}.",
            )
        if brief.mode != "repurpose" or not brief.source_text:
            return Review(must_keep_passed=True)
        scores = None
        if self._judge is not None:
            scores = await self._judge.ask_noul(
                {"original": brief.source_text, "rewrite": text},
                {"preserves_meaning": _MEANING},
            )
        if scores is None or "preserves_meaning" not in scores:
            return Review(
                must_keep_passed=True, feedback=UNAVAILABLE, judge_source="none"
            )
        score = float(scores["preserves_meaning"])
        verdict = "yes" if score >= 0.5 else "no"
        retry = verdict == "no" or score < self._min_confidence
        note = ""
        if retry:
            note = (
                f"A semantic judge flagged the previous rewrite (verdict={verdict}, "
                f"confidence={score:.2f}): preserve the source's meaning, claims, and intent "
                "much more faithfully."
            )
        return Review(
            must_keep_passed=True,
            judge_verdict=verdict,
            judge_confidence=score,
            judge_source="judge",
            needs_retry=retry,
            revision_note=note,
        )
