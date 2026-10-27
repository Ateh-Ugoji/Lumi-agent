"""Turns scores into ``pass``, ``regenerate`` or ``fail``. Thresholds come from ``AIConfig``.

``fail`` means the draft is not worth showing without a human look: invented facts or a
hopeless mean. ``regenerate`` means another guided attempt is likely to fix it.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from lumi_ai.config import AIConfig
from lumi_ai.evaluation.rubric import CRITICAL, GUIDANCE
from lumi_ai.evaluation.types import Decision


@dataclass(frozen=True, slots=True)
class QualityThresholds:
    min_criterion: float
    pass_mean: float
    fail_below: float
    min_style_similarity: float

    @classmethod
    def from_config(cls, config: AIConfig) -> QualityThresholds:
        return cls(
            config.quality_min_criterion,
            config.quality_pass_mean,
            config.quality_fail_below,
            config.quality_min_style_similarity,
        )

    @property
    def version(self) -> str:
        return (
            f"crit{self.min_criterion:g}-mean{self.pass_mean:g}"
            f"-fail{self.fail_below:g}-sim{self.min_style_similarity:g}"
        )


def decide(
    failures: Sequence[str],
    scores: Mapping[str, float],
    similarity: float | None,
    thresholds: QualityThresholds,
    reasons: Mapping[str, str] | None = None,
) -> tuple[Decision, str]:
    """The decision and the critique that the next attempt receives (empty on ``pass``)."""
    reasons = reasons or {}
    problems: list[str] = [f"Fix: {f}." for f in failures]
    decision: Decision = "pass"
    if failures:
        decision = "regenerate"
    if scores:
        mean = sum(scores.values()) / len(scores)
        for name, value in scores.items():
            if value < thresholds.min_criterion:
                why = reasons.get(name, "")
                problems.append(
                    f"{name} scored {value:.2f}: {why + '. ' if why else ''}"
                    f"Improve it: {GUIDANCE.get(name, name)}."
                )
        if mean < thresholds.pass_mean and not any(
            v < thresholds.min_criterion for v in scores.values()
        ):
            problems.append(
                f"The overall score is {mean:.2f}, below {thresholds.pass_mean:g}: "
                "make the post sharper and more specific."
            )
        if problems:
            decision = "regenerate"
        if (
            scores.get(CRITICAL, 1.0) < thresholds.fail_below
            or mean < thresholds.fail_below
        ):
            decision = "fail"
    if (
        thresholds.min_style_similarity > 0
        and similarity is not None
        and similarity < thresholds.min_style_similarity
    ):
        problems.append(
            f"The style similarity to the author's posts is {similarity:.2f}, below "
            f"{thresholds.min_style_similarity:g}: write closer to the author's own posts."
        )
        if decision == "pass":
            decision = "regenerate"
    return decision, " ".join(problems) if decision != "pass" else ""
