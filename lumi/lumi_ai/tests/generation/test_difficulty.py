import pytest

from lumi_ai.generation.difficulty import (
    ROUTE_TIERS,
    classify_by_rule,
    classify_difficulty,
    protected_tokens,
)
from lumi_ai.tests.generation.support import FakeJudge

SHORT = (
    "A calm thought about testing. " * 5
)  # 150 chars, fine for LinkedIn and X? (x target 0-280)


def test_tiers_follow_the_route() -> None:
    assert ROUTE_TIERS == {"easy": "small", "standard": "large", "hard": "large"}


def test_protected_tokens_drop_trailing_punctuation() -> None:
    assert protected_tokens("see https://a.io/x. cc @bob, ok") == [
        "https://a.io/x",
        "@bob",
    ]


def test_rule_easy_standard_hard() -> None:
    assert classify_by_rule("x" * 100, "x", ()) == "easy"
    assert (
        classify_by_rule("x" * 100, "linkedin", ()) == "standard"
    )  # below its target length
    assert classify_by_rule("x" * 100, "x", ("one phrase",)) == "standard"
    assert classify_by_rule("x" * 100, "x", ("a", "b", "c")) == "hard"
    assert classify_by_rule("x" * 281, "x", ()) == "hard"  # must be compressed
    assert (
        classify_by_rule("hi @a @b https://c.io", "x", ()) == "hard"
    )  # three protected items


@pytest.mark.asyncio
async def test_the_judge_decides_first() -> None:
    judge = FakeJudge(choice=["hard"])
    assert await classify_difficulty(judge, "x" * 100, "x", ()) == "hard"
    state, name = judge.choice_calls[0]
    assert name == "difficulty" and state["target_length_limit"] == 280


@pytest.mark.asyncio
@pytest.mark.parametrize("judge", [None, FakeJudge(), FakeJudge(choice=["impossible"])])
async def test_the_rule_answers_when_the_judge_cannot(judge) -> None:
    assert await classify_difficulty(judge, "x" * 100, "x", ()) == "easy"
