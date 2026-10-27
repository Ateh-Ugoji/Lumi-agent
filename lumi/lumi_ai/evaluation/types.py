"""Shapes of an evaluation. No imports from ``generation``: the generation types import these."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

Decision = Literal["pass", "regenerate", "fail"]
JudgeName = Literal["jev", "groq-small", "rules"]


@dataclass(frozen=True, slots=True)
class RubricResult:
    """Scores 0..1 for every criterion, each with a one-line reason, and who produced them."""

    scores: Mapping[str, float]
    reasons: Mapping[str, str]
    source: JudgeName


@dataclass(frozen=True, slots=True)
class Evaluation:
    decision: Decision
    scores: Mapping[str, float]  # empty when no semantic judge answered
    reasons: Mapping[str, str]
    deterministic_failures: tuple[str, ...]
    style_similarity: float | None  # 0..1, None when there is nothing to compare with
    judge: JudgeName  # "rules" = no semantic judge answered, only the deterministic checks ran
    config_version: str
    critique: str = ""  # what the next attempt must fix; empty when it passes

    @property
    def mean_score(self) -> float | None:
        return (
            round(sum(self.scores.values()) / len(self.scores), 6)
            if self.scores
            else None
        )
