"""Evaluates one draft: deterministic checks, style similarity, rubric judges, gate.

Judges run in order (Jev, then the small LLM). If neither answers, the evaluation says so
(``judge="rules"``) and relies on the deterministic checks alone, instead of inventing scores.
A draft that already breaks a hard rule is not sent to any judge: it will be regenerated anyway.
"""

from __future__ import annotations

from collections.abc import Sequence

from lumi_ai.config import AIConfig
from lumi_ai.evaluation.checks import all_failures
from lumi_ai.evaluation.gate import QualityThresholds, decide
from lumi_ai.evaluation.rubric import RubricScorer
from lumi_ai.evaluation.style import StyleReference, StyleReferencer
from lumi_ai.evaluation.types import Evaluation
from lumi_ai.generation.platforms import rules_for
from lumi_ai.generation.types import GenerationBrief
from lumi_ai.ports import EvaluationRecord

NO_JUDGE = "no semantic judge answered; only the deterministic checks ran"


class Evaluator:
    def __init__(
        self,
        scorers: Sequence[RubricScorer],
        config: AIConfig | None = None,
        *,
        style: StyleReferencer | None = None,
    ) -> None:
        self._scorers = tuple(scorers)
        self._thresholds = QualityThresholds.from_config(config or AIConfig())
        self._style = style or StyleReferencer(None)

    async def evaluate(self, brief: GenerationBrief, text: str) -> Evaluation:
        rules = rules_for(brief.platform)
        failures = all_failures(brief, text)
        reasons: dict[str, str] = {}
        reference = await self._style.reference(brief, text)
        if reference.warning:
            reasons["style_similarity"] = reference.warning
        if failures:
            decision, critique = decide(
                failures, {}, reference.similarity, self._thresholds
            )
            return self._build(
                decision, {}, reasons, failures, reference, "rules", critique
            )
        for scorer in self._scorers:
            result = await scorer.score(brief, text, rules, reference.examples)
            if result is not None:
                decision, critique = decide(
                    (),
                    result.scores,
                    reference.similarity,
                    self._thresholds,
                    result.reasons,
                )
                return self._build(
                    decision,
                    dict(result.scores),
                    {**reasons, **result.reasons},
                    failures,
                    reference,
                    result.source,
                    critique,
                )
        decision, critique = decide((), {}, reference.similarity, self._thresholds)
        return self._build(
            decision,
            {},
            {**reasons, "judge": NO_JUDGE},
            failures,
            reference,
            "rules",
            critique,
        )

    def _build(
        self,
        decision,
        scores,
        reasons,
        failures,
        reference: StyleReference,
        judge,
        critique,
    ):
        return Evaluation(
            decision=decision,
            scores=scores,
            reasons=reasons,
            deterministic_failures=tuple(failures),
            style_similarity=reference.similarity,
            judge=judge,
            config_version=self._thresholds.version,
            critique=critique,
        )


def to_record(
    brief: GenerationBrief, draft: str, evaluation: Evaluation, attempt_id: int
) -> EvaluationRecord:
    return EvaluationRecord(
        profile_id=brief.profile_id,
        platform=brief.platform,
        draft=draft,
        decision=evaluation.decision,
        scores=dict(evaluation.scores),
        reasons=dict(evaluation.reasons),
        deterministic_failures=evaluation.deterministic_failures,
        style_similarity=evaluation.style_similarity,
        judge=evaluation.judge,
        config_version=evaluation.config_version,
        attempt_id=attempt_id,
    )
