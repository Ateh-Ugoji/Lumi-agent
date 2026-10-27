import pytest

from lumi_ai.config import AIConfig
from lumi_ai.evaluation.evaluator import Evaluator
from lumi_ai.evaluation.reviewer import QualityReviewer
from lumi_ai.generation.context import ContextBuilder
from lumi_ai.generation.enforcement import EnforcementReviewer
from lumi_ai.generation.flow import GenerationService
from lumi_ai.generation.tools import build
from lumi_ai.tests.evaluation.support import FakeEvalStore, ScriptedScorer, result
from lumi_ai.tests.fakes import FakeRepurpose, FakeVoice
from lumi_ai.tests.generation.support import FakeJudge, TierLLM, brief, reply
from lumi_ai.tools import ToolDeps, build_registry
from lumi_ai.tools.registry import ToolContext

SRC = "We shipped the new dashboard today. See https://acme.io/new @acme"
GOOD = "Our new dashboard is live. https://acme.io/new @acme"
JUDGE_OK = {"preserves_meaning": 0.95}


def rig(script, scorers, *, judge=None, evals=None):
    judge = judge or FakeJudge(choice=["standard"], noul=[JUDGE_OK] * 4)
    llm = TierLLM(script)
    store = FakeRepurpose()
    evals = evals if evals is not None else FakeEvalStore()
    reviewer = QualityReviewer(EnforcementReviewer(judge), Evaluator(scorers))
    service = GenerationService(
        llm,
        ContextBuilder(FakeVoice()),
        reviewer,
        store,
        judge=judge,
        evaluations=evals,
    )
    return service, llm, store, evals


@pytest.mark.asyncio
async def test_a_passing_draft_saves_one_evaluation_keyed_by_its_attempt() -> None:
    service, llm, _store, evals = rig(
        [reply(GOOD)], [ScriptedScorer("jev", [result()])]
    )
    out = await service.run(brief(source_text=SRC), AIConfig())
    [rec] = evals.records
    assert (
        rec.attempt_id == out.attempt.id
        and rec.decision == "pass"
        and rec.judge == "jev"
    )
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
    assert [r.attempt_id for r in evals.records] == [s.id for s in out.saved]
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
async def test_an_evaluation_that_cannot_be_saved_is_a_warning_and_the_draft_survives() -> (
    None
):
    evals = FakeEvalStore(fail=RuntimeError("db down"))
    service, _llm, store, _ = rig(
        [reply(GOOD)], [ScriptedScorer("jev", [result()])], evals=evals
    )
    out = await service.run(brief(source_text=SRC), AIConfig())
    assert len(store.requests) == 1 and out.draft.text == GOOD
    assert "was not saved: db down" in out.warnings[0]


@pytest.mark.asyncio
async def test_without_an_eval_store_nothing_is_saved_but_the_flow_runs() -> None:
    service, *_ = rig([reply(GOOD)], [ScriptedScorer("jev", [result()])])
    service._evaluations = None
    out = await service.run(brief(source_text=SRC), AIConfig())
    assert out.warnings == ()
