"""Peer winner selection: baseline-relative, computed in code, no LLM and no network.

Ported from ``app/analysis/winners.py``. Rules (``PeerConfig``):
- the baseline of each account comes only from *eligible* posts (>= 24 h old, inside the 28-day
  window, views present, not a deletion suspect), through the same math the user's own posts use;
- a post wins only when it beats its account's own median by ``MIN_OUTLIER_FOR_WINNER`` (1.5x).
  There is no absolute views floor, so a small account is never judged by a big account's numbers;
- pinned, reply, repost, boosted-suspect and too-young posts never win;
- ``MAX_WINNERS_PER_ACCOUNT`` and ``TOP_N_WINNERS`` cap the set; below ``MIN_WINNERS_FOR_REPORT``
  the selection is ``insufficient_data`` and the thresholds are never lowered to fill a quota.

Differences from the legacy file: a counter that was not reported is ``None`` in the metrics (the
legacy turned it into 0 for the ratios), and ``outlier_views`` is ``None`` when the account has
no positive median.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

from lumi_ai.competitors.metrics import (
    BaselineCandidate,
    MetricSample,
    compute_baseline,
    eligible_baseline_samples,
    engagement_total,
)
from lumi_ai.competitors.schemas.peer import (
    AccountBaseline,
    PeerConfig,
    PostFormat,
    PostStats,
)

_EMOJI_RE = re.compile("[\U0001f1e6-\U0001f1ff\U0001f300-\U0001faff☀-➿️]")
_HASHTAG_RE = re.compile(r"(?<!\w)#\w+", re.UNICODE)
_LINK_RE = re.compile(r"https?://|t\.co/")


@dataclass(frozen=True)
class ScrapedPost:
    """One normalized peer post, whatever the source produced. ``views=None`` means missing."""

    post_id: str
    handle: str
    created_at: datetime
    text: str
    views: int | None
    likes: int | None = None
    replies: int | None = None
    reposts: int | None = None
    quotes: int | None = None
    bookmarks: int | None = None
    url: str | None = None
    is_pinned: bool = False
    is_reply: bool = False
    is_repost: bool = False
    is_deleted_suspect: bool = False
    thread_texts: list[str] = field(default_factory=list)
    format: PostFormat = "single"


@dataclass
class WinnerSelection:
    """Outcome of `select_winners` — feeds `NicheFrameworkReport.status`."""

    status: Literal["ok", "insufficient_data"]
    winners: list[PostStats]
    baselines: dict[str, AccountBaseline]
    excluded: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    @property
    def insufficient_reason(self) -> str | None:
        if self.status == "ok":
            return None
        return (
            f"only {len(self.winners)} winners found "
            f"(need {PeerConfig.MIN_WINNERS_FOR_REPORT}); thresholds were not lowered"
        )


def build_account_baseline(
    handle: str,
    posts: Sequence[ScrapedPost],
    *,
    followers: int | None = None,
    now: datetime | None = None,
) -> AccountBaseline:
    """Baseline for one account — same exclusion + percentile math as own posts."""
    now = now or datetime.now(UTC)
    candidates = [
        BaselineCandidate(
            published_at=p.created_at,
            is_deleted_suspect=p.is_deleted_suspect,
            sample=MetricSample(views=p.views, engagement=_engagement_total(p)),
        )
        for p in posts
    ]
    samples = eligible_baseline_samples(candidates, now=now)
    result = compute_baseline(samples)
    posts_per_week = None
    if posts:
        span_days = max(
            (now - min(p.created_at for p in posts)).total_seconds() / 86400.0, 1.0
        )
        posts_per_week = round(len(posts) / (span_days / 7.0), 2)
    return AccountBaseline(
        handle=handle.lstrip("@"),
        followers=followers,
        posts_scanned=result.n_posts,
        median_views=result.median_views,
        median_engagement=result.median_engagement,
        p75_views=result.p75_views,
        posts_per_week=posts_per_week,
        baseline_reliable=result.baseline_reliable,
    )


def _ratio(
    numerator: int | None, denominator: int | None, digits: int = 4
) -> float | None:
    """``numerator / denominator``, or ``None`` when either side is missing or the denominator is 0."""
    if numerator is None or not denominator:
        return None
    return round(numerator / denominator, digits)


def build_post_metrics(
    post: ScrapedPost,
    baseline: AccountBaseline,
    *,
    now: datetime | None = None,
    hours_since_prev: float | None = None,
    hours_to_next: float | None = None,
) -> PostStats | None:
    """Computed metrics for one scraped post. ``None`` when views are missing."""
    if post.views is None:
        return None
    now = now or datetime.now(UTC)
    text = post.text
    first_line = text.split("\n", 1)[0]
    total = _engagement_total(post)
    views = post.views

    return PostStats(
        post_id=post.post_id,
        handle=post.handle.lstrip("@"),
        url=post.url,
        created_at=post.created_at,
        age_hours=round((now - post.created_at).total_seconds() / 3600.0, 2),
        text=text,
        thread_texts=list(post.thread_texts),
        format=post.format,
        views=views,
        likes=post.likes,
        replies=post.replies,
        reposts=post.reposts,
        quotes=post.quotes,
        bookmarks=post.bookmarks,
        engagement_total=total,
        engagement_rate_views=_ratio(total, views),
        outlier_views=round(views / baseline.median_views, 4)
        if baseline.median_views > 0
        else None,
        outlier_engagement=(
            round(total / baseline.median_engagement, 4)
            if total is not None and baseline.median_engagement > 0
            else None
        ),
        reply_to_like=_ratio(post.replies, post.likes),
        repost_to_like=_ratio(post.reposts, post.likes),
        bookmark_to_like=_ratio(post.bookmarks, post.likes),
        char_count=len(text),
        line_count=text.count("\n") + 1,
        hook_word_count=len(first_line.split()),
        hashtag_count=len(_HASHTAG_RE.findall(text)),
        emoji_count=len(_EMOJI_RE.findall(text)),
        has_external_link=bool(_LINK_RE.search(text)),
        thread_length=len(post.thread_texts) + 1 if post.thread_texts else None,
        day_of_week=post.created_at.weekday(),  # Monday=0, matches the schema
        hour_utc=post.created_at.hour,
        hours_since_prev=hours_since_prev,
        hours_to_next=hours_to_next,
        is_pinned=post.is_pinned,
        is_reply=post.is_reply,
        is_repost=post.is_repost,
    )


def build_account_metrics(
    posts: Sequence[ScrapedPost],
    baseline: AccountBaseline,
    *,
    now: datetime | None = None,
) -> list[PostStats]:
    """All buildable posts for one account, oldest first so gaps can be measured."""
    ordered = sorted(posts, key=lambda p: p.created_at)
    out: list[PostStats] = []
    for i, post in enumerate(ordered):
        prev_gap = next_gap = None
        if i > 0:
            prev_gap = round(
                (post.created_at - ordered[i - 1].created_at).total_seconds() / 3600.0,
                2,
            )
        if i < len(ordered) - 1:
            next_gap = round(
                (ordered[i + 1].created_at - post.created_at).total_seconds() / 3600.0,
                2,
            )
        metrics = build_post_metrics(
            post, baseline, now=now, hours_since_prev=prev_gap, hours_to_next=next_gap
        )
        if metrics is not None:
            out.append(metrics)
    return out


def select_winners(
    metrics_by_handle: Mapping[str, list[PostStats]],
    baselines: Mapping[str, AccountBaseline],
    *,
    now: datetime | None = None,
) -> WinnerSelection:
    """Pick baseline-relative winners. Pure: no network, no DB, no LLM."""
    now = now or datetime.now(UTC)
    warnings: list[str] = []
    excluded: dict[str, int] = {}
    eligible: list[PostStats] = []

    def _drop(reason: str, count: int = 1) -> None:
        excluded[reason] = excluded.get(reason, 0) + count

    for handle, posts in metrics_by_handle.items():
        baseline = baselines.get(handle) or baselines.get(handle.lstrip("@"))
        if baseline is None:
            warnings.append(f"{handle}: no baseline — excluded from winner selection")
            _drop("no_baseline", len(posts))
            continue
        if not baseline.baseline_reliable:
            warnings.append(
                f"{handle}: baseline unreliable ({baseline.posts_scanned} posts, "
                f"need {PeerConfig.MIN_ACCOUNT_SAMPLE}) — excluded from winner selection"
            )
            _drop("baseline_unreliable", len(posts))
            continue

        per_account: list[PostStats] = []
        for post in posts:
            if post.is_pinned:
                _drop("pinned")
            elif post.is_reply:
                _drop("reply")
            elif post.is_repost:
                _drop("repost")
            elif post.is_boosted_suspect:
                _drop("boosted_suspect")
            elif post.age_hours < PeerConfig.MIN_POST_AGE_HOURS:
                _drop("too_young")
            elif (
                post.outlier_views is None
                or post.outlier_views < PeerConfig.MIN_OUTLIER_FOR_WINNER
            ):
                _drop("not_an_outlier")
            else:
                per_account.append(post)

        per_account.sort(key=lambda p: p.outlier_views or 0.0, reverse=True)
        eligible.extend(per_account[: PeerConfig.MAX_WINNERS_PER_ACCOUNT])
        if len(per_account) > PeerConfig.MAX_WINNERS_PER_ACCOUNT:
            _drop(
                "per_account_cap", len(per_account) - PeerConfig.MAX_WINNERS_PER_ACCOUNT
            )

    eligible.sort(key=lambda p: p.outlier_views or 0.0, reverse=True)
    winners = eligible[: PeerConfig.TOP_N_WINNERS]
    if len(eligible) > PeerConfig.TOP_N_WINNERS:
        _drop("top_n_cap", len(eligible) - PeerConfig.TOP_N_WINNERS)

    return WinnerSelection(
        status="ok"
        if len(winners) >= PeerConfig.MIN_WINNERS_FOR_REPORT
        else "insufficient_data",
        winners=winners,
        baselines={h: b for h, b in baselines.items()},
        excluded=excluded,
        warnings=warnings,
    )


def _engagement_total(post: ScrapedPost) -> int | None:
    """Sum only the counters that were reported; ``None`` when none was."""
    return engagement_total(
        post.likes, post.replies, post.reposts, post.quotes, post.bookmarks
    )
