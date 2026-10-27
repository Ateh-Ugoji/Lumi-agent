"""Tests for the peer pipeline's deterministic core (Prompt 1): baseline + winners.

Everything here is computed in code — no Xpoz, no LLM, no DB.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from lumi_ai.competitors.schemas.peer import AccountBaseline, PeerConfig, PostStats
from lumi_ai.competitors.winners import (
    ScrapedPost,
    WinnerSelection,
    build_account_baseline,
    build_post_metrics,
    select_winners,
)

NOW = datetime(2026, 10, 26, 12, 0, tzinfo=UTC)
MEDIAN = 1000.0


def _baseline(
    handle: str = "a",
    *,
    n: int = 40,
    reliable: bool = True,
    median_views: float = MEDIAN,
) -> AccountBaseline:
    return AccountBaseline(
        handle=handle,
        posts_scanned=n,
        median_views=median_views,
        median_engagement=100.0,
        p75_views=1500.0,
        baseline_reliable=reliable,
    )


def _post(
    handle: str = "a",
    *,
    views: int = 1500,
    age_hours: float = 48.0,
    baseline: AccountBaseline | None = None,
    **kwargs,
) -> PostStats:
    """Build real metrics through the production path (scraped post -> computed)."""
    post_id = kwargs.pop("post_id", f"{handle}-{views}-{age_hours}-{kwargs}")
    scraped = ScrapedPost(
        post_id=post_id,
        handle=handle,
        created_at=NOW - timedelta(hours=age_hours),
        text="hello world",
        views=views,
        likes=10,
        replies=2,
        reposts=1,
        **kwargs,
    )
    metrics = build_post_metrics(scraped, baseline or _baseline(handle), now=NOW)
    assert metrics is not None, "test post must have views"
    return metrics


def _select(posts: list[PostStats], **baselines) -> WinnerSelection:
    by_handle: dict[str, list[PostStats]] = {}
    for post in posts:
        by_handle.setdefault(post.handle, []).append(post)
    defaults = {h: _baseline(h) for h in by_handle}
    defaults.update(baselines)
    return select_winners(by_handle, defaults, now=NOW)


# ---------------------------------------------------------------- baseline
def test_baseline_excludes_young_missing_and_out_of_window_posts() -> None:
    posts = [
        ScrapedPost("1", "a", NOW - timedelta(hours=48), "x", views=1000),
        ScrapedPost("2", "a", NOW - timedelta(hours=6), "x", views=99_999),  # too young
        ScrapedPost(
            "3", "a", NOW - timedelta(days=200), "x", views=99_999
        ),  # out of window
        ScrapedPost(
            "4", "a", NOW - timedelta(days=10), "x", views=None
        ),  # missing views
    ]
    baseline = build_account_baseline("a", posts, now=NOW)
    assert baseline.posts_scanned == 1
    assert baseline.median_views == 1000.0


def test_baseline_reliability_threshold() -> None:
    thin = [
        ScrapedPost(str(i), "a", NOW - timedelta(days=10, hours=i), "x", views=1000)
        for i in range(20)
    ]
    assert build_account_baseline("a", thin, now=NOW).baseline_reliable is False
    thick = [
        ScrapedPost(str(i), "a", NOW - timedelta(days=10, hours=i), "x", views=1000)
        for i in range(40)
    ]
    assert build_account_baseline("a", thick, now=NOW).baseline_reliable is True


def test_missing_views_never_become_metrics() -> None:
    scraped = ScrapedPost("1", "a", NOW - timedelta(hours=48), "x", views=None)
    assert build_post_metrics(scraped, _baseline(), now=NOW) is None


def test_missing_optional_metrics_stay_none() -> None:
    metrics = _post(views=3000, quotes=None, bookmarks=None)
    assert metrics.quotes is None
    assert metrics.bookmarks is None
    assert metrics.outlier_views == 3.0


# ---------------------------------------------------------------- winners
def test_winner_threshold_boundary_is_exclusive() -> None:
    selection = _select([_post(views=1500), _post(views=1499, post_id="b")])
    assert [w.views for w in selection.winners] == [1500], "exact 1.5x must win"
    assert selection.excluded["not_an_outlier"] == 1, "1.49x must not win"


def test_pinned_reply_repost_and_young_are_excluded() -> None:
    selection = _select(
        [
            _post(views=5000, post_id="pinned", is_pinned=True),
            _post(views=5000, post_id="reply", is_reply=True),
            _post(views=5000, post_id="repost", is_repost=True),
            _post(views=5000, post_id="young", age_hours=12),
            _post(views=5000, post_id="clean"),
        ]
    )
    assert [w.post_id for w in selection.winners] == ["clean"]
    assert selection.excluded["pinned"] == 1
    assert selection.excluded["reply"] == 1
    assert selection.excluded["repost"] == 1
    assert selection.excluded["too_young"] == 1


def test_the_bar_is_each_accounts_own_average_not_a_fixed_number() -> None:
    """No fixed views floor: small accounts can win small, big accounts must win big."""
    small = _baseline("s", median_views=100.0)
    big = _baseline("b", median_views=10_000.0)
    selection = _select(
        [
            _post(
                "s", views=150, post_id="small_win", baseline=small
            ),  # 1.5x own median
            _post(
                "s", views=60, post_id="small_lose", baseline=small
            ),  # 0.6x own median
            _post(
                "b", views=600, post_id="big_lose", baseline=big
            ),  # 0.06x own median, >500 views
            _post(
                "b", views=15_000, post_id="big_win", baseline=big
            ),  # 1.5x own median
        ],
        s=small,
        b=big,
    )
    assert sorted(w.post_id for w in selection.winners) == ["big_win", "small_win"]


def test_per_account_cap_stops_one_account_dominating() -> None:
    posts = [_post(views=1500 + i * 100, post_id=f"a{i}") for i in range(8)]
    selection = _select(posts)
    assert len(selection.winners) == PeerConfig.MAX_WINNERS_PER_ACCOUNT
    assert selection.excluded["per_account_cap"] == 3


def test_global_top_n_cap_keeps_the_largest_outliers() -> None:
    posts = [
        _post(handle, views=1500 + i * 10 + offset, post_id=f"{handle}{i}")
        for offset, handle in enumerate("abcde")  # 5 accounts x 6 eligible posts
        for i in range(6)
    ]
    selection = _select(posts)
    assert len(selection.winners) == PeerConfig.TOP_N_WINNERS
    assert selection.excluded["per_account_cap"] == 5  # one extra per account
    assert selection.excluded["top_n_cap"] == 5  # 25 -> 20
    outliers = [w.outlier_views for w in selection.winners]
    assert outliers == sorted(outliers, reverse=True)


def test_few_winners_is_insufficient_data_and_thresholds_are_not_lowered() -> None:
    selection = _select(
        [
            _post(views=1500),
            _post(views=2000, post_id="b"),
            _post(views=900, post_id="c"),
        ]
    )
    assert selection.status == "insufficient_data"
    assert len(selection.winners) == 2, "the 900-view post is still not a winner"
    assert "thresholds were not lowered" in (selection.insufficient_reason or "")


def test_enough_winners_is_ok() -> None:
    # spread across accounts so the per-account cap does not apply
    posts = [
        _post(chr(ord("a") + i), views=1500 + i, post_id=f"w{i}")
        for i in range(PeerConfig.MIN_WINNERS_FOR_REPORT)
    ]
    assert _select(posts).status == "ok"


def test_unreliable_or_missing_baseline_excludes_the_account_with_a_warning() -> None:
    posts = [_post("a", views=5000, post_id="a1"), _post("b", views=5000, post_id="b1")]
    selection = select_winners(
        {"a": [posts[0]], "b": [posts[1]]},
        {"a": _baseline("a", reliable=False)},
        now=NOW,
    )
    assert selection.winners == []
    assert selection.excluded["baseline_unreliable"] == 1
    assert selection.excluded["no_baseline"] == 1
    assert len(selection.warnings) == 2
    assert selection.status == "insufficient_data"
