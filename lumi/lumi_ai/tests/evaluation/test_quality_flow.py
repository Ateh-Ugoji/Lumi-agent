import pytest

from lumi_ai.config import AIConfig
from lumi_ai.evaluation.evaluator import Evaluator
from lumi_ai.evaluation.reviewer import QualityReviewer
from lumi_ai.generation.context import ContextBuilder
from lumi_ai.generation.enforcement import EnforcementReviewer
from lumi_ai.generation.flow import GenerationService
from lumi_ai.generation.tools import build
from lumi_ai.tests.evaluation.support import ScriptedScorer, result
from lumi_ai.tests.fakes import FakeRepurpose, FakeVoice
from lumi_ai.tests.generation.support import FakeJudge, TierLLM, brief, reply
from lumi_ai.tools import ToolDeps, build_registry
from lumi_ai.tools.registry import ToolContext

SRC = "We shipped the new dashboard today. See https://acme.io/new @acme"
GOOD = "Our new dashboard is live. https://acme.io/new @acme"
JUDGE_OK = {"preserves_meaning": 0.95}


class _Evals:
    """The evaluations the flow handed to the store, as ``(attempt_no, record)`` pairs."""

    def __init__(self, store):
        self._store = store

    @property
    def records(self):
        return [
            rec
            for request in self._store.requests
            for _no, rec in sorted(request["evaluations"].items())
        ]


def rig(script, scorers, *, judge=None):
    judge = judge or FakeJudge(choice=["standard"], noul=[JUDGE_OK] * 4)
    llm = TierLLM(script)
    store = FakeRepurpose()
    reviewer = QualityReviewer(EnforcementReviewer(judge), Evaluator(scorers))
    service = GenerationService(
        llm,
        ContextBuilder(FakeVoice()),
        reviewer,
        store,
        judge=judge,
    )
    return service, llm, store, _Evals(store)


@pytest.mark.asyncio
async def test_a_passing_draft_hands_one_evaluation_keyed_by_its_attempt_no() -> None:
    service, llm, store, evals = rig([reply(GOOD)], [ScriptedScorer("jev", [result()])])
    out = await service.run(brief(source_text=SRC), AIConfig())
    [rec] = evals.records
    assert list(store.requests[0]["evaluations"]) == [out.attempt.attempt_no]
    assert rec.decision == "pass" and rec.judge == "jev" and rec.draft == GOOD
    assert out.draft.text == GOOD and out.warnings == () and len(llm.tiers) == 1


@pytest.mark.asyncio
async def test_a_weak_criterion_triggers_a_regeneration_guided_by_the_critique() -> (
    None
):
    scorer = ScriptedScorer("jev", [result("jev", 0.9, hook=0.2), result("jev", 0.9)])
    service, llm, _store, evals = rig([reply(GOOD), reply(GOOD + " Now.")], [scorer])
    out = await service.run(brief(source_text=SRC), AIConfig())
    retry_prompt = llm.seen[1][-1]["content"]
    assert "hook scored 0.20" in retry_prompt
    assert [r.decision for r in evals.records] == ["regenerate", "pass"]
    assert [s.attempt_no for s in out.saved] == [1, 2]
    assert [r.draft for r in evals.records] == [GOOD, GOOD + " Now."]
    assert out.attempt.attempt_no == 2  # the passing attempt wins


@pytest.mark.asyncio
async def test_the_best_attempt_wins_when_none_passes() -> None:
    scorer = ScriptedScorer(
        "jev",
        [
            result("jev", 0.9, hook=0.2),
            result("jev", 0.9, hook=0.45),
            result("jev", 0.9, hook=0.1, no_invented_facts=0.1),
        ],
    )
    service, _llm, _store, evals = rig([reply(GOOD)] * 3, [scorer])
    out = await service.run(brief(source_text=SRC), AIConfig())
    assert [r.decision for r in evals.records] == ["regenerate", "regenerate", "fail"]
    assert out.attempt.attempt_no == 2  # highest mean among the regenerate decisions
    assert out.review.needs_retry  # surfaced as needing review


@pytest.mark.asyncio
async def test_no_semantic_judge_is_visible_in_the_result_not_hidden() -> None:
    service, _llm, store, evals = rig([reply(GOOD)], [ScriptedScorer("jev", [None])])
    registry = build_registry(
        ToolDeps(profiles=None, repurpose=store), extra=build(service)
    )
    out = await registry.call(
        ToolContext(profile_id=1, config=AIConfig()),
        "repurpose_caption",
        {"reason": "t", "platform": "linkedin", "source_text": SRC},
    )
    assert out["needs_review"] is True
    assert out["evaluation"]["judge"] == "rules" and out["evaluation"]["scores"] == {}
    assert evals.records[0].judge == "rules"


@pytest.mark.asyncio
async def test_a_store_that_rejects_the_request_fails_the_whole_generation() -> None:
    """Evaluations travel with the attempts: there is no half-saved state to warn about."""
    judge = FakeJudge(choice=["standard"], noul=[JUDGE_OK] * 4)
    store = FakeRepurpose(fail=RuntimeError("db down"))
    service = GenerationService(
        TierLLM([reply(GOOD)]),
        ContextBuilder(FakeVoice()),
        QualityReviewer(
            EnforcementReviewer(judge),
            Evaluator([ScriptedScorer("jev", [result()])]),
        ),
        store,
        judge=judge,
    )
    with pytest.raises(RuntimeError, match="db down"):
        await service.run(brief(source_text=SRC), AIConfig())
    assert store.requests == []


@pytest.mark.asyncio
async def test_every_attempt_of_a_request_carries_its_evaluation() -> None:
    scorer = ScriptedScorer("jev", [result("jev", 0.9, hook=0.2), result("jev", 0.9)])
    service, _llm, store, _ = rig([reply(GOOD), reply(GOOD + " Now.")], [scorer])
    await service.run(brief(source_text=SRC), AIConfig())
    assert sorted(store.requests[0]["evaluations"]) == [1, 2]
