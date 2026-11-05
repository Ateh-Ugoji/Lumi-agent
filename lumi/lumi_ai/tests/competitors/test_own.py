from __future__ import annotations

from datetime import timedelta

from lumi_ai.competitors.own import compute_own_lift
from lumi_ai.ports import PostMetrics, PostOut
from lumi_ai.tests.competitors.support import NOW


def _post(i: int, views: int | None, **kw) -> PostOut:
    return PostOut(
        id=i,
        profile_id=1,
        platform="x",
        external_id=f"p{i}",
        text=f"post {i}",
        published_at=NOW - timedelta(days=2, hours=i * 6),
        kind=kw.pop("kind", "original"),
        metrics=None if views is None else PostMetrics(views=views, likes=10),
        **kw,
    )


def test_a_post_that_beats_the_own_median_wins_and_the_table_is_built() -> None:
    posts = [_post(i, 1000 + i) for i in range(30)] + [_post(100, 5000)]
    result = compute_own_lift(posts, "me", now=NOW)
    assert result.status == "ok"
    assert result.winner_post_ids == ("p100",)
    assert result.baseline.baseline_reliable
    assert result.dimensions_covered == ("format",)


def test_no_winner_is_insufficient_data_and_the_bar_stays_put() -> None:
    result = compute_own_lift([_post(i, 1000) for i in range(30)], "me", now=NOW)
    assert result.status == "insufficient_data" and result.n_winners == 0
    assert "never lowered" in (result.reason or "")


def test_no_posts_never_raises_and_invents_nothing() -> None:
    result = compute_own_lift([], "me", now=NOW)
    assert result.status == "insufficient_data" and result.lift_rows == ()
    assert result.n_eligible == 0


def test_missing_views_are_not_zeros() -> None:
    posts = [_post(i, None) for i in range(10)] + [_post(50, 800)]
    result = compute_own_lift(posts, "me", now=NOW)
    assert result.n_eligible == 1  # only the post that reported views is judged


def test_flagged_replies_and_reposts_never_win() -> None:
    base = [_post(i, 1000 + i) for i in range(30)]
    extra = [
        _post(90, 9000, is_deleted_suspect=True),
        _post(91, 9000, kind="reply"),
        _post(92, 9000, kind="retweet"),
    ]
    result = compute_own_lift(base + extra, "me", now=NOW)
    assert result.winner_post_ids == ()


def test_a_thin_baseline_is_flagged_as_a_hint() -> None:
    result = compute_own_lift([_post(i, 1000 + i) for i in range(5)], "me", now=NOW)
    assert result.warnings and not result.baseline.baseline_reliable
