import json

import pytest

from lumi_ai.evaluation.evaluator import NO_JUDGE, Evaluator, to_record
from lumi_ai.evaluation.rubric import CRITERIA, JevScorer, LLMScorer, parse_rubric
from lumi_ai.evaluation.style import StyleReferencer
from lumi_ai.generation.platforms import rules_for
from lumi_ai.tests.agent.harness import FakeLLM, say
from lumi_ai.tests.evaluation.support import ScriptedScorer, all_scores, result
from lumi_ai.tests.fakes import make_post
from lumi_ai.tests.generation.support import FakeJudge, StubRetriever, brief

B = brief(platform="linkedin", mode="topic", topic="pricing", source_text=None)
POST = "We changed our pricing and learned something real about value."
RULES = rules_for("linkedin")


def rubric_json(score: float = 0.8, **overrides) -> str:
    data = {
        n: {"score": overrides.get(n, score), "reason": f"why {n}"} for n in CRITERIA
    }
    return json.dumps(data)


@pytest.mark.asyncio
async def test_jev_scorer_needs_every_criterion() -> None:
    judge = FakeJudge(noul=[all_scores(0.8), {"hook": 0.9}, None])
    scorer = JevScorer(judge)
    ok = await scorer.score(B, POST, RULES, ["example"])
    assert ok.source == "jev" and ok.scores["hook"] == 0.8
    assert ok.reasons["hook"] == "judge score 0.80 (strong)"
    assert await scorer.score(B, POST, RULES, []) is None  # partial verdict
    assert await scorer.score(B, POST, RULES, []) is None
    state, questions = judge.noul_calls[0]
    assert state["post"] == POST and state["author_example_posts"] == ["example"]
    assert set(questions) == set(CRITERIA) and "source_caption" not in state


@pytest.mark.asyncio
async def test_llm_scorer_returns_scores_and_reasons() -> None:
    llm = FakeLLM([say(f"```json\n{rubric_json(0.7, hook=0.3)}\n```")])
    out = await LLMScorer(llm).score(B, POST, RULES, [])
    assert out.source == "groq-small" and out.scores["hook"] == 0.3
    assert out.reasons["hook"] == "why hook"
    assert POST in llm.seen[0][-1]["content"]


@pytest.mark.asyncio
@pytest.mark.parametrize("reply", ["not json", '{"hook": {"score": 1}}', "[]"])
async def test_llm_scorer_gives_no_verdict_on_bad_output(reply: str) -> None:
    assert await LLMScorer(FakeLLM([say(reply)])).score(B, POST, RULES, []) is None


@pytest.mark.asyncio
async def test_llm_scorer_gives_no_verdict_when_the_provider_fails() -> None:
    assert (
        await LLMScorer(FakeLLM([])).score(B, POST, RULES, []) is None
    )  # script exhausted raises


def test_parse_rubric_clamps_scores() -> None:
    data = {n: {"score": 7, "reason": ""} for n in CRITERIA}
    out = parse_rubric(data, "groq-small")
    assert set(out.scores.values()) == {1.0} and out.reasons["hook"] == "score 1.00"


@pytest.mark.asyncio
async def test_first_scorer_that_answers_decides_and_names_itself() -> None:
    jev = ScriptedScorer("jev", [None])
    llm = ScriptedScorer("groq-small", [result("groq-small", 0.9)])
    ev = await Evaluator([jev, llm]).evaluate(B, POST)
    assert (ev.decision, ev.judge) == ("pass", "groq-small")
    assert len(jev.calls) == 1 and len(llm.calls) == 1


@pytest.mark.asyncio
async def test_no_judge_means_rules_only_and_says_so() -> None:
    ev = await Evaluator([ScriptedScorer("jev", [None])]).evaluate(B, POST)
    assert (ev.decision, ev.judge, ev.scores) == ("pass", "rules", {})
    assert ev.reasons["judge"] == NO_JUDGE


@pytest.mark.asyncio
async def test_a_hard_failure_skips_the_judges() -> None:
    scorer = ScriptedScorer("jev", [result()])
    ev = await Evaluator([scorer]).evaluate(B, "Dash \u2014 here")
    assert ev.decision == "regenerate" and ev.judge == "rules" and scorer.calls == []
    assert "em dash" in ev.deterministic_failures[0] and "Fix:" in ev.critique


@pytest.mark.asyncio
async def test_weak_scores_produce_a_critique_for_the_next_attempt() -> None:
    ev = await Evaluator(
        [ScriptedScorer("jev", [result("jev", 0.9, specificity=0.2)])]
    ).evaluate(B, POST)
    assert ev.decision == "regenerate" and "specificity scored 0.20" in ev.critique
    assert ev.config_version == "crit0.5-mean0.7-fail0.3-sim0"


@pytest.mark.asyncio
async def test_style_similarity_is_the_clamped_mean_of_the_nearest_posts() -> None:
    retriever = StubRetriever(
        own=[make_post(1, "close one"), make_post(2, "close two")]
    )
    scorer = ScriptedScorer("jev", [result()])
    ev = await Evaluator([scorer], style=StyleReferencer(retriever, k=2)).evaluate(
        B, POST
    )
    assert ev.style_similarity == 0.8  # StubRetriever returns distance 0.2
    assert scorer.calls[0][2] == (
        "close one",
        "close two",
    )  # the same posts anchor the judge


@pytest.mark.asyncio
async def test_style_without_a_corpus_or_with_a_failing_index_is_none_with_a_reason() -> (
    None
):
    for retriever in (
        None,
        StubRetriever(),
        StubRetriever(error=RuntimeError("chroma down")),
    ):
        ev = await Evaluator(
            [ScriptedScorer("jev", [result()])], style=StyleReferencer(retriever)
        ).evaluate(B, POST)
        assert ev.style_similarity is None and "style_similarity" in ev.reasons
        assert ev.decision == "pass"


@pytest.mark.asyncio
async def test_to_record_carries_everything_the_store_needs() -> None:
    ev = await Evaluator([ScriptedScorer("jev", [result()])]).evaluate(B, POST)
    rec = to_record(B, POST, ev, 42)
    assert (rec.attempt_id, rec.profile_id, rec.platform, rec.draft) == (
        42,
        1,
        "linkedin",
        POST,
    )
    assert (rec.decision, rec.judge, rec.config_version) == (
        "pass",
        "jev",
        ev.config_version,
    )
    assert set(rec.scores) == set(CRITERIA) and rec.reasons["hook"] == "reason for hook"
