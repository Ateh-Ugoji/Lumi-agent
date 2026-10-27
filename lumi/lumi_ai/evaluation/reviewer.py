"""The reviewer the flow uses in production: enforcement first, then the quality evaluation.

Enforcement keeps its own verdict (``must_keep_passed``, the meaning judge). The evaluation
adds the rubric, the style checks and the gate. A draft is retried if either one says so, and
the critique of the retry joins both.
"""

from __future__ import annotations

from dataclasses import replace

from lumi_ai.evaluation.evaluator import Evaluator
from lumi_ai.generation.types import GenerationBrief, Review, Reviewer


class QualityReviewer:
    def __init__(self, enforcement: Reviewer, evaluator: Evaluator) -> None:
        self._enforcement = enforcement
        self._evaluator = evaluator

    async def review(self, brief: GenerationBrief, text: str) -> Review:
        base = await self._enforcement.review(brief, text)
        evaluation = await self._evaluator.evaluate(brief, text)
        if not base.must_keep_passed:
            note = (
                evaluation.critique or base.revision_note
            )  # the critique already lists the hard failures
        else:
            note = " ".join(n for n in (base.revision_note, evaluation.critique) if n)
        return replace(
            base,
            evaluation=evaluation,
            needs_retry=base.needs_retry or evaluation.decision != "pass",
            revision_note=note,
        )
