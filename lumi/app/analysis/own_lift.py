"""Own-post lift table — the user's posts vs their own baseline.

Same winner rule and same lift math as the peer pipeline:
- winner = outlier_views >= PeerConfig.MIN_OUTLIER_FOR_WINNER against the
  account's OWN median (baseline-relative, never an absolute threshold);
- lift rows come from app.analysis.lift.build_lift_table, the exact function
  the peer side uses — own and peer results are comparable by construction
  (profile_extract_fixes.md Step 2/3).

Dimensions: only computed dimensions (format) carry values until blind
tagging lands (own_tagging.py is a pending-row stub until the peer extract /
Runtime Prompt A is merged). LLM dimensions simply have no values yet, so
build_lift_table emits no rows for them — nothing is invented.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlmodel import select

from app.analysis.lift import LiftItem, build_lift_table
from app.analysis.metrics import (
    BaselineCandidate,
    MetricSample,
    build_own_post_metrics,
    compute_baseline,
    eligible_baseline_samples,
    engagement_total,
    final_metrics,
)
from app.database import session_scope
from app.models.post import MetricSnapshot, Post
from app.models.profile import Profile, ProfileBaseline
from app.schemas.peer import PeerConfig

log = logging.getLogger(__name__)


def _baseline_from_candidates(candidates: list[BaselineCandidate]):
    """Shared exclusion + percentile math (app.analysis.metrics)."""
    return compute_baseline(eligible_baseline_samples(candidates))


async def compute_own_lift(profile_id: int, *, persist_baseline: bool = False) -> dict[str, Any]:
    """Baseline + winner lift table for the user's own posts.

    Pure local DB work — no network, no LLM. `persist_baseline=True` appends
    a profile_baseline row (bootstrap path); reports pass False to stay
    read-only. Never raises on empty data: insufficient data returns
    status="insufficient_data" with empty rows, never fabricated numbers.
    """
    async with session_scope() as session:
        profile = await session.get(Profile, profile_id)
        if profile is None:
            return {"status": "failed", "reason": f"no profile with id {profile_id}"}
        handle = profile.handle.lstrip("@")

        posts = (await session.exec(select(Post).where(Post.profile_id == profile_id))).all()
        post_ids = [p.id for p in posts if p.id is not None]
        snapshots: list[MetricSnapshot] = []
        if post_ids:
            snapshots = (
                await session.exec(
                    select(MetricSnapshot).where(MetricSnapshot.post_id.in_(post_ids))
                )
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

        baseline = _baseline_from_candidates(candidates)

        if persist_baseline:
            session.add(
                ProfileBaseline(
                    profile_id=profile_id,
                    window_days=PeerConfig.LOOKBACK_DAYS,
                    n_posts=baseline.n_posts,
                    median_views=baseline.median_views,
                    median_engagement=baseline.median_engagement,
                    p75_views=baseline.p75_views,
                    baseline_reliable=baseline.baseline_reliable,
                )
            )
            await session.flush()

        items: list[LiftItem] = []
        n_with_metrics = 0
        for post in posts:
            if post.is_deleted_suspect:
                continue  # flagged data never informs winners — the gap stays flagged
            pm = build_own_post_metrics(post, snapshots, baseline, handle=handle)
            if pm is None:
                continue
            n_with_metrics += 1
            items.append(
                LiftItem(
                    attributes={"format": pm.format},
                    is_winner=pm.outlier_views >= PeerConfig.MIN_OUTLIER_FOR_WINNER,
                    outlier_views=pm.outlier_views,
                )
            )

        rows = build_lift_table(items)
        n_winners = sum(1 for i in items if i.is_winner)

        if baseline.n_posts == 0:
            status = "insufficient_data"
            reason = "no posts with final metrics eligible for the baseline"
        elif n_winners == 0:
            status = "insufficient_data"
            reason = (
                f"no post reached {PeerConfig.MIN_OUTLIER_FOR_WINNER}x the own median "
                f"({baseline.median_views:.0f} views) — thresholds are never lowered to fill a quota"
            )
        else:
            status = "ok"
            reason = None

        result: dict[str, Any] = {
            "profile_id": profile_id,
            "handle": handle,
            "status": status,
            "n_eligible": n_with_metrics,
            "n_winners": n_winners,
            "baseline": {
                "n_posts": baseline.n_posts,
                "median_views": baseline.median_views,
                "median_engagement": baseline.median_engagement,
                "p75_views": baseline.p75_views,
                "baseline_reliable": baseline.baseline_reliable,
            },
            "lift_rows": [r.model_dump() for r in rows],
            "dimensions_covered": ["format"],  # computed only; LLM dimensions land with tagging
        }
        if reason is not None:
            result["reason"] = reason

    log.info(
        "own lift profile %s: status=%s eligible=%d winners=%d rows=%d",
        profile_id,
        result["status"],
        result["n_eligible"],
        result["n_winners"],
        len(result["lift_rows"]),
    )
    return result
