"""Doubles for the evaluation tests (test-only)."""

from __future__ import annotations

from lumi_ai.evaluation.rubric import CRITERIA
from lumi_ai.evaluation.types import RubricResult


def all_scores(value: float = 0.9, **overrides: float) -> dict[str, float]:
    return {**dict.fromkeys(CRITERIA, value), **overrides}


class ScriptedScorer:
    """A RubricScorer that returns scripted results; ``None`` means no verdict."""

    def __init__(self, name, results):
        self.name = name
        self.results = list(results)
        self.calls = []

    async def score(self, brief, text, rules, examples):
        self.calls.append((brief, text, tuple(examples)))
        return self.results.pop(0) if self.results else None


def result(source="jev", value: float = 0.9, **overrides: float) -> RubricResult:
    scores = all_scores(value, **overrides)
    return RubricResult(scores, {n: f"reason for {n}" for n in scores}, source)


class FakeEvalStore:
    def __init__(self, fail: Exception | None = None):
        self.records = []
        self.fail = fail

    async def save_evaluation(self, record):
        if self.fail:
            raise self.fail
        self.records.append(record)
        return len(self.records)

    async def list_evaluations(self, profile_id, *, limit=50):
        return list(self.records)[-limit:]
