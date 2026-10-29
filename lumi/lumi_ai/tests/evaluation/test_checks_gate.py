import pytest

from lumi_ai.config import AIConfig
from lumi_ai.evaluation.checks import all_failures, forbidden_patterns
from lumi_ai.evaluation.gate import QualityThresholds, decide
from lumi_ai.tests.evaluation.support import all_scores
from lumi_ai.tests.generation.support import brief

T = QualityThresholds.from_config(AIConfig())


def test_em_dash_stock_phrases_and_leaked_json_are_forbidden() -> None:
    assert forbidden_patterns("Plain post, nothing odd.") == []
    assert "em dash" in forbidden_patterns("We shipped \u2014 finally")[0]
    assert (
        "stock phrase" in forbidden_patterns("In today's fast-paced world, we ship")[0]
    )
    assert "Let's dive in" in forbidden_patterns("Let's dive in!")[0]
    assert forbidden_patterns('```json\n{"text": "x"}```')
    assert forbidden_patterns('{"text": "leaked"}')


def test_all_failures_joins_platform_rules_and_style_patterns() -> None:
    b = brief(platform="x", mode="topic", topic="t", must_keep=("Acme",))
    fails = all_failures(b, "a \u2014 " + "b" * 300)
    assert len(fails) == 3  # too long, missing phrase, em dash


def test_pass_needs_every_criterion_and_the_mean() -> None:
    assert decide((), all_scores(0.9), None, T) == ("pass", "")


def test_a_weak_criterion_regenerates_with_its_reason_and_guidance() -> None:
    decision, critique = decide(
        (), all_scores(0.9, hook=0.4), None, T, {"hook": "opens with a cliché"}
    )
    assert decision == "regenerate"
    assert "hook scored 0.40" in critique and "opens with a cliché" in critique
    assert "earns the next one" in critique


def test_a_low_mean_with_every_criterion_above_the_floor_still_regenerates() -> None:
    decision, critique = decide((), all_scores(0.65), None, T)
    assert decision == "regenerate" and "overall score is 0.65" in critique


@pytest.mark.parametrize(
    "scores", [all_scores(0.9, no_invented_facts=0.1), all_scores(0.2)]
)
def test_invented_facts_or_a_hopeless_mean_fail(scores) -> None:
    assert decide((), scores, None, T)[0] == "fail"


def test_deterministic_failures_regenerate_even_without_scores() -> None:
    decision, critique = decide(("too long",), {}, None, T)
    assert decision == "regenerate" and "Fix: too long." in critique


def test_style_similarity_gates_only_when_a_threshold_is_set() -> None:
    assert decide((), all_scores(0.9), 0.1, T)[0] == "pass"  # default 0 = recorded only
    strict = QualityThresholds.from_config(AIConfig(quality_min_style_similarity=0.5))
    decision, critique = decide((), all_scores(0.9), 0.1, strict)
    assert decision == "regenerate" and "style similarity" in critique
    assert (
        decide((), all_scores(0.9), None, strict)[0] == "pass"
    )  # no corpus: not a reason to block


def test_thresholds_come_from_the_config_and_are_versioned() -> None:
    t = QualityThresholds.from_config(AIConfig(quality_pass_mean=0.8))
    assert t.pass_mean == 0.8 and "mean0.8" in t.version
    assert decide((), all_scores(0.75), None, t)[0] == "regenerate"
