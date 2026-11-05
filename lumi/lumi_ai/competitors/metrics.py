"""Baseline math shared by competitors and the user's own posts.

Own and peer baselines go through the same ``eligible_baseline_samples`` + ``compute_baseline``, so
a "winner" means the same thing on both sides. Missing views are never read as 0.
Ported from ``lumi/legacy/app/analysis/metrics.py``; the snapshot/DB parts stay in Django (apps/profiles).
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from lumi_ai.competitors.schemas.peer import PeerConfig


@dataclass(frozen=True)
class MetricSample:
    views: int | None
    engagement: int | None


@dataclass(frozen=True)
class BaselineCandidate:
    """One post up for baseline inclusion, before exclusions."""

    published_at: datetime
    is_deleted_suspect: bool
    sample: MetricSample


@dataclass(frozen=True)
class BaselineResult:
    median_views: float
    median_engagement: float
    p75_views: float
    n_posts: int
    baseline_reliable: bool  # n_posts >= PeerConfig.MIN_ACCOUNT_SAMPLE


def percentile(values: list[float], p: float) -> float:
    """Linear-interpolation percentile (p in 0..1). Empty -> 0.0 (callers check ``n_posts``)."""
    if not values:
        return 0.0
    xs = sorted(values)
    if len(xs) == 1:
        return xs[0]
    k = (len(xs) - 1) * p
    lo = int(k)
    hi = min(lo + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def eligible_baseline_samples(
    candidates: list[BaselineCandidate],
    *,
    now: datetime | None = None,
    min_age_hours: float = PeerConfig.MIN_POST_AGE_HOURS,
    lookback_days: int = PeerConfig.LOOKBACK_DAYS,
) -> list[MetricSample]:
    """Apply the shared exclusions, then return samples with views present.

    Excluded: deletion suspects, posts younger than ``min_age_hours`` (still growing), posts older
    than ``lookback_days`` and samples without views.
    """
    now = now or datetime.now(UTC)
    cutoff = now - timedelta(days=lookback_days)
    out: list[MetricSample] = []
    for c in candidates:
        if c.is_deleted_suspect:
            continue
        age_hours = (now - c.published_at).total_seconds() / 3600.0
        if age_hours < min_age_hours or c.published_at < cutoff:
            continue
        if c.sample.views is None:
            continue
        out.append(c.sample)
    return out


def compute_baseline(samples: list[MetricSample]) -> BaselineResult:
    """Median/p75 views and median engagement over eligible samples."""
    views = [float(s.views) for s in samples if s.views is not None]
    engagement = [float(s.engagement) for s in samples if s.engagement is not None]
    n = len(views)
    return BaselineResult(
        median_views=statistics.median(views) if views else 0.0,
        median_engagement=statistics.median(engagement) if engagement else 0.0,
        p75_views=percentile(views, 0.75),
        n_posts=n,
        baseline_reliable=n >= PeerConfig.MIN_ACCOUNT_SAMPLE,
    )


def engagement_total(
    likes: int | None,
    comments: int | None,
    shares: int | None,
    quotes: int | None = None,
    bookmarks: int | None = None,
) -> int | None:
    """Sum of the counters that were reported. ``None`` when none was (never a fake 0)."""
    present = [v for v in (likes, comments, shares, quotes, bookmarks) if v is not None]
    return int(sum(present)) if present else None


def x_algorithm_weighted_engagement(
    likes: int | None,
    comments: int | None,
    shares: int | None,
    quotes: int | None = None,
    bookmarks: int | None = None,
) -> float | None:
    """Weights interactions using X Heavy Ranker's reverse-engineered importance.

    Weights:
    - Replies/Comments: 13.5x (highest conversational driver)
    - Retweets/Shares: 1.0x
    - Likes: 1.0x (standard passive signal)
    - Quotes: 3.0x (opinionated amplification)
    - Bookmarks: 2.0x (high save-intent signal)
    """
    present = [v for v in (likes, comments, shares, quotes, bookmarks) if v is not None]
    if not present:
        return None
    l = float(likes or 0)
    c = float(comments or 0)
    s = float(shares or 0)
    q = float(quotes or 0)
    b = float(bookmarks or 0)
    return round((1.0 * l) + (13.5 * c) + (1.0 * s) + (3.0 * q) + (2.0 * b), 2)


def calculate_tweepcred_ratio_health(
    followers_count: int, following_count: int
) -> dict[str, Any]:
    """Evaluates an account's following-to-follower ratio against TweepCred algorithms.

    Source: twitter/the-algorithm/src/scala/com/twitter/graph/batch/job/tweepcred/Reputation.scala
    If numFollowings > 2,500 and ratio > 0.6:
      divFactor = exp(3.0 * (ratio - 0.6) * ln(ln(numFollowings))) capped at 50x.
    """
    followers = max(0, int(followers_count))
    following = max(0, int(following_count))
    ratio = (1.0 + following) / (1.0 + followers)

    thresh_friends = 2500
    thresh_ratio = 0.6
    max_div_factor = 50.0

    if following > thresh_friends and ratio > thresh_ratio:
        log_log_friends = math.log(math.log(following))
        exponent = 3.0 * (ratio - thresh_ratio) * log_log_friends
        div_factor = min(max_div_factor, max(1.0, math.exp(exponent)))
        is_penalized = True
    else:
        div_factor = 1.0
        is_penalized = False

    reach_retention = 1.0 / div_factor
    reach_penalty_pct = round((1.0 - reach_retention) * 100.0, 1)

    if div_factor >= 10.0:
        status = "critical"
    elif div_factor > 1.05:
        status = "warning"
    else:
        status = "healthy"

    # Advice calculation: how many accounts must be unfollowed to get ratio <= 0.6
    unfollow_target = 0
    if is_penalized:
        max_allowed_following = int(math.floor(0.6 * followers))
        unfollow_target = max(0, following - max_allowed_following)

    return {
        "following_to_followers_ratio": round(ratio, 3),
        "is_penalized": is_penalized,
        "division_factor": round(div_factor, 2),
        "reach_loss_percentage": reach_penalty_pct,
        "status": status,
        "unfollow_target_to_fix": unfollow_target,
    }

