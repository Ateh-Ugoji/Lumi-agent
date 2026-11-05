"""Golden suite: hand-written drafts with the decision the quality gate must reach.

THE CASES ARE SYNTHETIC. They are written by the developers, not drawn from posts that the
user accepted or rejected, and their recorded rubric scores are what a judge *should* say.
Offline the suite replays those scores, so it checks the gate and the deterministic rules.
With ``--live`` it asks the real judges, which measures how far they agree with these
expectations. Neither number says how the judges rate the user's real posts: replace the
cases with accepted and rejected drafts before trusting a threshold.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lumi_ai.config import AIConfig
from lumi_ai.evaluation.evaluator import Evaluator
from lumi_ai.evaluation.rubric import CRITERIA, RubricScorer
from lumi_ai.evaluation.types import Evaluation, RubricResult
from lumi_ai.generation.types import GenerationBrief

CASES_PATH = Path(__file__).with_name("cases.json")


@dataclass(frozen=True, slots=True)
class GoldenCase:
    id: str
    brief: GenerationBrief
    text: str
    expected_decision: str
    expected_judge: str
    scores: dict[str, float] | None
    note: str = ""
    synthetic: bool = True


def load_cases(path: Path = CASES_PATH) -> list[GoldenCase]:
    cases: list[GoldenCase] = []
    for raw in json.loads(path.read_text(encoding="utf-8")):
        brief = GenerationBrief(
            profile_id=1,
            platform=raw["platform"],
            mode=raw["mode"],
            source_text=raw["source_text"],
            topic=raw["topic"],
            must_keep=tuple(raw["must_keep"]),
        )
        scores = raw["scores"]
        if scores is not None and set(scores) != set(CRITERIA):
            raise ValueError(
                f"case {raw['id']}: scores must cover exactly {sorted(CRITERIA)}"
            )
        cases.append(
            GoldenCase(
                raw["id"],
                brief,
                raw["text"],
                raw["expected"]["decision"],
                raw["expected"]["judge"],
                scores,
                raw.get("note", ""),
                raw.get("synthetic", True),
            )
        )
    return cases


class RecordedScorer:
    """Replays the recorded scores of each case, found by its draft. Offline only."""

    name = "jev"

    def __init__(self, cases: Sequence[GoldenCase]) -> None:
        self._by_text = {c.text: c.scores for c in cases}

    async def score(self, brief, text, rules, examples) -> RubricResult | None:
        scores = self._by_text.get(text)
        if scores is None:
            return None
        return RubricResult(
            scores, {n: f"recorded score {v:.2f}" for n, v in scores.items()}, "jev"
        )


@dataclass(frozen=True, slots=True)
class CaseResult:
    case: GoldenCase
    evaluation: Evaluation

    @property
    def agrees(self) -> bool:
        return self.evaluation.decision == self.case.expected_decision


@dataclass(frozen=True, slots=True)
class SuiteReport:
    results: tuple[CaseResult, ...]

    @property
    def agreement(self) -> float:
        return (
            sum(r.agrees for r in self.results) / len(self.results)
            if self.results
            else 0.0
        )

    @property
    def regeneration_rate(self) -> float:
        n = len(self.results)
        return (
            sum(r.evaluation.decision == "regenerate" for r in self.results) / n
            if n
            else 0.0
        )

    @property
    def mismatches(self) -> tuple[CaseResult, ...]:
        return tuple(r for r in self.results if not r.agrees)

    @property
    def judges(self) -> dict[str, int]:
        return dict(Counter(r.evaluation.judge for r in self.results))

    @property
    def decisions(self) -> dict[str, int]:
        return dict(Counter(r.evaluation.decision for r in self.results))

    def as_dict(self) -> dict[str, Any]:
        return {
            "cases": len(self.results),
            "synthetic": all(r.case.synthetic for r in self.results),
            "agreement": round(self.agreement, 4),
            "regeneration_rate": round(self.regeneration_rate, 4),
            "decisions": self.decisions,
            "judges": self.judges,
            "mismatches": [
                {
                    "id": r.case.id,
                    "expected": r.case.expected_decision,
                    "got": r.evaluation.decision,
                    "judge": r.evaluation.judge,
                    "scores": dict(r.evaluation.scores),
                }
                for r in self.mismatches
            ],
        }


async def run_suite(
    cases: Sequence[GoldenCase],
    scorers: Sequence[RubricScorer],
    config: AIConfig | None = None,
) -> SuiteReport:
    evaluator = Evaluator(scorers, config)
    return SuiteReport(
        tuple([CaseResult(c, await evaluator.evaluate(c.brief, c.text)) for c in cases])
    )
