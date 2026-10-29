"""One generation: context, classify, write, review, regenerate with feedback, save once.

The request and all its attempts are saved in ONE transaction AFTER the work. A run that
produces no usable draft raises :class:`GenerationFailed` and saves nothing, so no orphan
request is left behind (the legacy tool saved the request first).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from lumi_ai.agent.support import Completer
from lumi_ai.config import AIConfig
from lumi_ai.evaluation.evaluator import to_evaluation_in
from lumi_ai.generation.context import ContextBuilder
from lumi_ai.generation.difficulty import ROUTE_TIERS, classify_difficulty
from lumi_ai.generation.platforms import rules_for
from lumi_ai.generation.types import (
    Difficulty,
    Draft,
    GenerationBrief,
    GenerationOutcome,
    Review,
    Reviewer,
)
from lumi_ai.generation.writer import DraftUnusable, Revision, Writer
from lumi_ai.ports import (
    AttemptIn,
    AttemptOut,
    RepurposeStore,
    SemanticJudge,
    Tier,
)

log = logging.getLogger(__name__)


class GenerationFailed(Exception):
    """No attempt produced a usable draft. Nothing was saved."""


@dataclass(frozen=True, slots=True)
class GenerationResult:
    request_id: int
    saved: tuple[AttemptOut, ...]
    outcome: GenerationOutcome
    warnings: tuple[str, ...] = ()  # e.g. an evaluation that could not be saved

    @property
    def attempt(self) -> AttemptOut:
        return self.saved[self.outcome.chosen]

    @property
    def draft(self) -> Draft:
        return self.outcome.drafts[self.outcome.chosen]

    @property
    def review(self) -> Review:
        return self.outcome.reviews[self.outcome.chosen]


_DECISION_RANK = {"fail": 0, "regenerate": 1, "pass": 2}


def best_attempt(reviews: list[Review]) -> int:
    """The draft to show: passes the hard checks, then the judge, then the later (revised) one."""

    def score(i: int) -> tuple[bool, bool, int, bool, float, float, int]:
        r = reviews[i]
        ev = r.evaluation
        return (
            r.must_keep_passed,
            not r.needs_retry,
            _DECISION_RANK[ev.decision] if ev else 0,
            r.judge_verdict == "yes",
            r.judge_confidence or 0.0,
            (ev.mean_score or 0.0) if ev else 0.0,
            i,
        )

    return max(range(len(reviews)), key=score)


class GenerationService:
    def __init__(
        self,
        llm: Completer,
        context: ContextBuilder,
        reviewer: Reviewer,
        store: RepurposeStore,
        *,
        judge: SemanticJudge | None = None,
    ) -> None:
        self._writer = Writer(llm)
        self._context = context
        self._reviewer = reviewer
        self._store = store
        self._judge = judge

    async def run(self, brief: GenerationBrief, config: AIConfig) -> GenerationResult:
        rules = rules_for(brief.platform)
        context, used = await self._context.build(brief, config)
        label = await self._route(brief)
        base_tier = ROUTE_TIERS[label]

        drafts: list[Draft] = []
        reviews: list[Review] = []
        attempts: list[AttemptIn] = []
        unusable: list[str] = []
        revision: Revision | None = None
        for attempt_no in range(1, 2 + max(0, config.generation_max_regenerations)):
            tier: Tier = base_tier if attempt_no == 1 else "large"
            try:
                draft = await self._writer.write(
                    brief, rules, context, tier=tier, revision=revision
                )
            except DraftUnusable as exc:
                log.warning("attempt %d produced no usable draft: %s", attempt_no, exc)
                unusable.append(str(exc))
                revision = Revision(
                    drafts[-1].text if drafts else "(none: no usable draft yet)",
                    f"Your last reply was unusable: {exc}. Answer with ONE JSON object "
                    'that has a "text" string.',
                )
                continue
            review = await self._reviewer.review(brief, draft.text)
            drafts.append(draft)
            reviews.append(review)
            attempts.append(
                AttemptIn(
                    platform=brief.platform,
                    output=draft.text,
                    attempt_no=attempt_no,
                    must_keep_passed=review.must_keep_passed,
                    tier=draft.tier,
                    model=draft.model,
                    provider=draft.provider,
                    judge_verdict=review.judge_verdict,
                    judge_confidence=review.judge_confidence,
                    is_fallback=draft.is_fallback,
                )
            )
            if not review.needs_retry:
                break
            revision = Revision(draft.text, review.revision_note)

        if not attempts:
            raise GenerationFailed(
                "the model gave no usable draft in "
                f"{len(unusable)} attempt(s): {'; '.join(unusable)}"
            )

        request_id, saved = await self._store.create_request_with_attempts(
            brief.profile_id,
            brief.source_text or brief.topic or "",
            label,
            attempts,
            mode=brief.mode,
            brief=_brief_text(brief) if brief.mode == "topic" else None,
            source_post_id=brief.source_post_id,
            evaluations={
                a.attempt_no: to_evaluation_in(brief, a.output, r.evaluation)
                for a, r in zip(attempts, reviews, strict=True)
                if r.evaluation is not None
            },
        )
        outcome = GenerationOutcome(
            brief=brief,
            route_label=label,
            attempts=tuple(attempts),
            reviews=tuple(reviews),
            drafts=tuple(drafts),
            chosen=best_attempt(reviews),
            context=used,
        )
        return GenerationResult(request_id, tuple(saved), outcome, ())

    async def _route(self, brief: GenerationBrief) -> Difficulty:
        if brief.mode == "topic" or not brief.source_text:
            return "standard"  # writing from nothing is never a light restyle
        return await classify_difficulty(
            self._judge, brief.source_text, brief.platform, brief.must_keep
        )


def _brief_text(brief: GenerationBrief) -> str:
    lines = [f"topic: {brief.topic}"]
    if brief.goal:
        lines.append(f"goal: {brief.goal}")
    return "\n".join(lines)
