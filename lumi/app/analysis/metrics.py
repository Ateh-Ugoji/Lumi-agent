"""Shared baseline + own-post metric math.

Rule from profile_extract_fixes.md Step 2: own and peer baselines must be
computed IDENTICALLY — both sides go through `eligible_baseline_samples` +
`compute_baseline` here (peer Prompt 1 consumes the same functions; this module
is the one place percentile/median/exclusion math lives).

Snapshot policy (Step 2):
- every snapshot records age_hours (since publish)
- capture targets are 24h / 72h / 7d / 30d (nearest ingestion pass is fine)
- skip inserting when metrics are unchanged AND age > 7d — except when the pass
  crosses a target milestone (otherwise the 30d target would be unreachable)
- "final metrics" = the snapshot nearest 72h (`final_metrics`)
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.models.post import MetricSnapshot, Post
from app.models.profile import ProfileBaseline
from app.schemas.peer import PeerConfig, PostMetrics

TARGET_SNAPSHOT_AGE_HOURS = 72.0
MILESTONE_AGES_HOURS = (24.0, 72.0, 168.0, 720.0)  # 24h, 72h, 7d, 30d
UNCHANGED_SNAPSHOT_MAX_AGE_HOURS = 168.0  # >7d: unchanged inserts only on milestone crossings
MIN_REFRESH_GAP_HOURS = 6.0  # <=7d: unchanged posts refresh at most once per 6h

# (likes, comments, shares, views) — None means MISSING, never 0
MetricsTuple = tuple[int | None, int | None, int | None, int | None]

_EMOJI_RE = re.compile("[\U0001F1E6-\U0001F1FF\U0001F300-\U0001FAFF☀-➿️]")
_HASHTAG_RE = re.compile(r"(?<!\w)#\w+", re.UNICODE)
_LINK_RE = re.compile(r"https?://|t\.co/")


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


# --------------------------------------------------------------------------
# Pure math (own + peer call these — never fork the math)
# --------------------------------------------------------------------------
def percentile(values: list[float], p: float) -> float:
    """Linear-interpolation percentile (p in 0..1). Empty -> 0.0."""
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

    Excluded: is_deleted_suspect, posts younger than min_age_hours (still
    growing), posts older than lookback_days, and samples whose views are
    missing (NULL) — missing views can't inform a views baseline and must
    never be treated as 0.
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
    """Median/p75 views + median engagement over eligible samples."""
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


# --------------------------------------------------------------------------
# Snapshot policy
# --------------------------------------------------------------------------
def snapshot_age_hours(post: Post, snap: MetricSnapshot) -> float:
    """Age of the post at capture time (uses age_hours; falls back to timestamps)."""
    if snap.age_hours is not None:
        return snap.age_hours
    return (snap.captured_at - post.published_at).total_seconds() / 3600.0


def metrics_tuple(snap: MetricSnapshot) -> MetricsTuple:
    return (snap.likes, snap.comments, snap.shares, snap.views)


def engagement_total(snap: MetricSnapshot) -> int:
    """Sum of the metrics actually present — missing values contribute nothing."""
    return sum(v for v in (snap.likes, snap.comments, snap.shares) if v is not None)


def milestone_bucket(age_hours: float) -> int:
    """How many 24h/72h/7d/30d targets the age has crossed."""
    return sum(1 for m in MILESTONE_AGES_HOURS if age_hours >= m)


def should_insert_snapshot(
    prev_age_hours: float | None,
    prev_metrics: MetricsTuple | None,
    new_metrics: MetricsTuple,
    age_hours: float,
) -> bool:
    """Whether to append a snapshot (see module docstring for the policy)."""
    if prev_metrics is None or prev_age_hours is None:
        return True
    if new_metrics != prev_metrics:
        return True
    if milestone_bucket(age_hours) != milestone_bucket(prev_age_hours):
        return True  # crossed a 24h/72h/7d/30d target — capture the milestone
    if age_hours > UNCHANGED_SNAPSHOT_MAX_AGE_HOURS:
        return False  # stale & unchanged
    return (age_hours - prev_age_hours) >= MIN_REFRESH_GAP_HOURS


def final_metrics(post: Post, snapshots: list[MetricSnapshot]) -> MetricSnapshot | None:
    """The snapshot nearest the 72h target — the post's "final metrics" row."""
    mine = [s for s in snapshots if s.post_id == post.id]
    if not mine:
        return None
    return min(mine, key=lambda s: abs(snapshot_age_hours(post, s) - TARGET_SNAPSHOT_AGE_HOURS))


# --------------------------------------------------------------------------
# Own-post metrics: same PostMetrics shape the peer pipeline produces
# --------------------------------------------------------------------------
def build_own_post_metrics(
    post: Post,
    snapshots: list[MetricSnapshot],
    baseline: BaselineResult,
    *,
    handle: str,
    now: datetime | None = None,
    thread_length: int | None = None,
    hours_since_prev: float | None = None,
    hours_to_next: float | None = None,
) -> PostMetrics | None:
    """PostMetrics for one of the user's own posts, using final_metrics.

    Returns None when there is no final snapshot with views present (missing
    views can never be faked into an outlier score). quotes/bookmarks stay
    None — own-side storage for them doesn't exist yet (peer schema allows None).
    """
    now = now or datetime.now(UTC)
    fm = final_metrics(post, snapshots)
    if fm is None or fm.views is None:
        return None

    views = fm.views
    likes = fm.likes or 0
    comments = fm.comments or 0
    shares = fm.shares or 0
    total = engagement_total(fm)

    text = post.caption
    first_line = text.split("\n", 1)[0]
    age_hours = (now - post.published_at).total_seconds() / 3600.0
    length = thread_length or 1

    return PostMetrics(
        post_id=post.platform_post_id,
        handle=handle.lstrip("@"),
        url=f"https://x.com/{handle.lstrip('@')}/status/{post.platform_post_id}",
        created_at=post.published_at,
        age_hours=round(age_hours, 2),
        text=text,
        format="thread" if length > 1 else "single",
        views=views,
        likes=likes,
        replies=comments,
        reposts=shares,
        quotes=None,  # not stored for own posts — never default a missing metric to 0
        bookmarks=None,
        engagement_total=total,
        engagement_rate_views=round(total / views, 4) if views else 0.0,
        # neutral 1.0 only when there is no engagement baseline at all yet
        outlier_views=round(views / baseline.median_views, 4) if baseline.median_views > 0 else 1.0,
        outlier_engagement=(
            round(total / baseline.median_engagement, 4) if baseline.median_engagement > 0 else 1.0
        ),
        reply_to_like=round(comments / likes, 4) if likes else 0.0,
        repost_to_like=round(shares / likes, 4) if likes else 0.0,
        bookmark_to_like=0.0,  # bookmarks not stored for own posts
        char_count=len(text),
        line_count=text.count("\n") + 1,
        hook_word_count=len(first_line.split()),
        hashtag_count=len(_HASHTAG_RE.findall(text)),
        emoji_count=len(_EMOJI_RE.findall(text)),
        has_external_link=bool(_LINK_RE.search(text)),
        thread_length=length if length > 1 else None,
        day_of_week=post.published_at.weekday(),  # Monday=0, matches schema
        hour_utc=post.published_at.hour,
        hours_since_prev=hours_since_prev,
        hours_to_next=hours_to_next,
        is_pinned=False,  # pin state not exposed by either source yet
        is_reply=False,  # own posts, incl. self-reply thread parts (routed to posts)
        is_repost=False,
        is_boosted_suspect=False,
    )


# --------------------------------------------------------------------------
# DB-level baseline for the user's own account (bootstrap + reports use this)
# --------------------------------------------------------------------------
async def compute_profile_baseline(session, profile_id: int) -> ProfileBaseline:
    """Recompute the profile's baseline row from final_metrics. Caller commits."""
    from sqlmodel import select

    posts = (await session.exec(select(Post).where(Post.profile_id == profile_id))).all()
    post_ids = [p.id for p in posts if p.id is not None]
    snapshots: list[MetricSnapshot] = []
    if post_ids:
        snapshots = (
            await session.exec(select(MetricSnapshot).where(MetricSnapshot.post_id.in_(post_ids)))
        ).all()

    candidates: list[BaselineCandidate] = []
    for post in posts:
        fm = final_metrics(post, snapshots)
        if fm is None:
            continue
        candidates.append(
            BaselineCandidate(
                published_at=post.published_at,
                is_deleted_suspect=bool(post.is_deleted_suspect),
                sample=MetricSample(views=fm.views, engagement=engagement_total(fm)),
            )
        )

    result = compute_baseline(eligible_baseline_samples(candidates))
    row = ProfileBaseline(
        profile_id=profile_id,
        window_days=PeerConfig.LOOKBACK_DAYS,
        n_posts=result.n_posts,
        median_views=result.median_views,
        median_engagement=result.median_engagement,
        p75_views=result.p75_views,
        baseline_reliable=result.baseline_reliable,
    )
    session.add(row)
    await session.flush()
    return row
