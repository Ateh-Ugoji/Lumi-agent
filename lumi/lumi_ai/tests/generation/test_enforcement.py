import pytest

from lumi_ai.generation.enforcement import (
    UNAVAILABLE,
    EnforcementReviewer,
    deterministic_failures,
    hashtags,
)
from lumi_ai.tests.generation.support import FakeJudge, brief

SRC = "Shipped it. https://acme.io/new @acme"


def test_over_the_limit_is_a_hard_failure() -> None:
    fails = deterministic_failures(
        brief(platform="x", mode="topic", topic="t"), "a" * 281
    )
    assert fails and "280" in fails[0]
    assert not deterministic_failures(
        brief(platform="x", mode="topic", topic="t"), "a" * 280
    )


def test_must_keep_is_case_insensitive_and_names_what_is_missing() -> None:
    b = brief(mode="topic", topic="t", must_keep=("Acme Cloud", "v2"))
    assert not deterministic_failures(b, "Try ACME CLOUD v2 today")
    fails = deterministic_failures(b, "Try Acme Cloud today")
    assert fails == ["missing required phrase(s): v2"]


def test_links_and_mentions_of_the_source_must_survive_even_with_punctuation() -> None:
    b = brief(source_text="Read (https://acme.io/new). Thanks @acme!")
    assert not deterministic_failures(b, "Thanks @Acme, read https://acme.io/new now")
    fails = deterministic_failures(b, "Read it on our site")
    assert "https://acme.io/new" in fails[0] and "@acme" in fails[0]


def test_topic_mode_has_no_source_links_to_keep() -> None:
    assert not deterministic_failures(
        brief(mode="topic", topic="launch"), "no links here"
    )


def test_instagram_hashtag_cap_ignores_url_fragments() -> None:
    b = brief(platform="instagram", mode="topic", topic="t")
    assert hashtags("see https://x.io/a#section and #one #two") == ["#one", "#two"]
    assert not deterministic_failures(b, "#a #b #c #d #e")
    assert "6 hashtags" in deterministic_failures(b, "#a #b #c #d #e #f")[0]
    other = brief(platform="linkedin", mode="topic", topic="t")
    assert not deterministic_failures(
        other, "#a #b #c #d #e #f #g"
    )  # advice, not enforced


@pytest.mark.asyncio
async def test_hard_failure_skips_the_judge_and_asks_for_a_retry() -> None:
    judge = FakeJudge(noul=[{"preserves_meaning": 0.9}])
    review = await EnforcementReviewer(judge).review(brief(source_text=SRC), "no link")
    assert not review.must_keep_passed and review.needs_retry
    assert "lost link" in review.revision_note
    assert judge.noul_calls == []


@pytest.mark.asyncio
async def test_confident_yes_is_accepted() -> None:
    judge = FakeJudge(noul=[{"preserves_meaning": 0.92}])
    review = await EnforcementReviewer(judge).review(
        brief(source_text=SRC), "Out now: https://acme.io/new @acme"
    )
    assert review.must_keep_passed and not review.needs_retry
    assert (review.judge_verdict, review.judge_confidence) == ("yes", 0.92)
    assert judge.noul_calls[0][0]["original"] == SRC


@pytest.mark.asyncio
@pytest.mark.parametrize(("score", "verdict"), [(0.3, "no"), (0.6, "yes")])
async def test_a_no_or_an_unsure_yes_is_retried(score: float, verdict: str) -> None:
    judge = FakeJudge(noul=[{"preserves_meaning": score}])
    review = await EnforcementReviewer(judge).review(
        brief(source_text=SRC), "Out now: https://acme.io/new @acme"
    )
    assert review.judge_verdict == verdict and review.needs_retry
    assert "meaning" in review.revision_note


@pytest.mark.asyncio
@pytest.mark.parametrize("judge", [None, FakeJudge()])
async def test_no_judge_means_flagged_for_review_not_silently_approved(judge) -> None:
    review = await EnforcementReviewer(judge).review(
        brief(source_text=SRC), "Out now: https://acme.io/new @acme"
    )
    assert review.must_keep_passed and not review.needs_retry
    assert review.feedback == UNAVAILABLE and review.judge_source == "none"
    assert review.judge_verdict is None and review.judge_confidence is None


@pytest.mark.asyncio
async def test_topic_mode_runs_no_meaning_judge() -> None:
    judge = FakeJudge(noul=[{"preserves_meaning": 0.1}])
    review = await EnforcementReviewer(judge).review(
        brief(mode="topic", topic="launch", source_text=None), "A fresh post"
    )
    assert (
        review.must_keep_passed and not review.needs_retry and review.feedback is None
    )
    assert judge.noul_calls == []
