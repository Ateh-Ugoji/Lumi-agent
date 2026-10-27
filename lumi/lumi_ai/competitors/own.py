"""The user's own posts against their own baseline: same winner rule and lift math as the peers.

Ported from ``app/analysis/own_lift.py``. Pure: no network, no database, no model. The caller reads
the posts through ``PostStore`` and persists nothing here (the baseline row is ``PostStore.save_baseline``'s
job). A post wins when it beats the account's own median views by ``MIN_OUTLIER_FOR_WINNER``; the
bar is never lowered to fill a quota. Only the computed ``format`` dimension has values until the own
posts are tagged, so the other dimensions emit no rows rather than invented ones.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

from lumi_ai.competitors.lift import LiftItem, build_lift_table
from lumi_ai.competitors.schemas.peer import AccountBaseline, LiftRow, PeerConfig
from lumi_ai.competitors.winners import (
    ScrapedPost,
    build_account_baseline,
    build_account_metrics,
)
from lumi_ai.ports import PostOut


@dataclass(frozen=True, slots=True)
class OwnLift:
    status: Literal["ok", "insufficient_data"]
    baseline: AccountBaseline
    n_eligible: int  # posts with views that went into the table
    n_winners: int
    winner_post_ids: tuple[str, ...]  # external ids
    lift_rows: tuple[LiftRow, ...]
    reason: str | None = None
    dimensions_covered: tuple[str, ...] = ("format",)
    warnings: tuple[str, ...] = field(default_factory=tuple)


def scraped_from_own(post: PostOut, handle: str) -> ScrapedPost | None:
    """A stored own post as a ``ScrapedPost``. ``None`` for text-less posts. Missing views stay ``None``."""
    text = (post.text or "").strip()
    if not text:
        return None
    created = post.published_at
    if created.tzinfo is None:
        created = created.replace(tzinfo=UTC)
    m = post.metrics
    return ScrapedPost(
        post_id=post.external_id,
        handle=handle,
        created_at=created,
        text=text,
        views=m.views if m else None,
        likes=m.likes if m else None,
        replies=m.comments if m else None,
        reposts=m.shares if m else None,
        quotes=m.quotes if m else None,
        bookmarks=m.bookmarks if m else None,
        url=post.url,
        is_reply=post.kind == "reply",
        is_repost=post.kind == "retweet",
        is_deleted_suspect=post.is_deleted_suspect,
    )


def compute_own_lift(
    posts: Sequence[PostOut], handle: str, *, now: datetime | None = None
) -> OwnLift:
    """Baseline and winner lift of the user's own posts. Never raises on thin data."""
    now = now or datetime.now(UTC)
    scraped = [s for p in posts if (s := scraped_from_own(p, handle))]
    baseline = build_account_baseline(handle, scraped, now=now)
    # Flagged posts never inform winners: the gap stays visible instead of being filled.
    usable = [s for s in scraped if not s.is_deleted_suspect]
    metrics = build_account_metrics(usable, baseline, now=now)
    winners = [
        m
        for m in metrics
        if m.outlier_views is not None
        and m.outlier_views >= PeerConfig.MIN_OUTLIER_FOR_WINNER
        and not (m.is_reply or m.is_repost)
    ]
    winner_ids = {m.post_id for m in winners}
    rows = build_lift_table(
        [
            LiftItem(
                attributes={"format": m.format},
                is_winner=m.post_id in winner_ids,
                outlier_views=m.outlier_views,
            )
            for m in metrics
        ]
    )
    reason: str | None = None
    if baseline.posts_scanned == 0:
        reason = "no posts with final metrics are eligible for the baseline"
    elif not winners:
        reason = (
            f"no post reached {PeerConfig.MIN_OUTLIER_FOR_WINNER}x the own median "
            f"({baseline.median_views:.0f} views); thresholds are never lowered to fill a quota"
        )
    warnings = (
        ()
        if baseline.baseline_reliable
        else (
            f"baseline built from {baseline.posts_scanned} posts (< {PeerConfig.MIN_ACCOUNT_SAMPLE}): treat it as a hint",
        )
    )
    return OwnLift(
        status="ok" if reason is None else "insufficient_data",
        baseline=baseline,
        n_eligible=len(metrics),
        n_winners=len(winners),
        winner_post_ids=tuple(m.post_id for m in winners),
        lift_rows=tuple(rows),
        reason=reason,
        warnings=warnings,
    )
