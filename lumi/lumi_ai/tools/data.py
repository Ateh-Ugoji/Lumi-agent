"""Read tools over the profile's own posts: posts, replies/retweets and analytics."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from statistics import median
from typing import Any

from lumi_ai.ports import ActivityOut, PostOut, PostStore
from lumi_ai.tools.registry import ToolContext, ToolSpec

ANALYTICS_WINDOW_DAYS = 28
TOP_POSTS = 5
CAPTION_CHARS = 300


def _post_dict(post: PostOut) -> dict[str, Any]:
    return {
        "id": post.id,
        "platform": post.platform,
        "caption": post.text,
        "published_at": post.published_at.isoformat(),
        "kind": post.kind,
        "url": post.url,
    }


def _activity_dict(item: ActivityOut) -> dict[str, Any]:
    return {
        "kind": item.kind,
        "platform": item.platform,
        "caption": item.text,
        "published_at": item.published_at.isoformat(),
    }


def _sum_known(values: list[int | None]) -> int | None:
    """Sum of the reported values; ``None`` when nothing was reported (never a fake 0)."""
    known = [v for v in values if v is not None]
    return sum(known) if known else None


def compute_analytics(posts: list[PostOut], window_days: int) -> dict[str, Any]:
    """Aggregate stored metrics. A metric nobody reported stays ``None``."""
    with_metrics = [p for p in posts if p.metrics is not None]
    views = _sum_known([p.metrics.views for p in with_metrics if p.metrics])
    likes = _sum_known([p.metrics.likes for p in with_metrics if p.metrics])
    comments = _sum_known([p.metrics.comments for p in with_metrics if p.metrics])
    shares = _sum_known([p.metrics.shares for p in with_metrics if p.metrics])

    engagement = _sum_known([likes, comments, shares])
    engagement_rate = (
        round(engagement / views, 4) if engagement is not None and views else None
    )

    by_kind_views: dict[str, int] = defaultdict(int)
    by_day_views: dict[str, int] = defaultdict(int)
    by_day_saves: dict[str, int] = defaultdict(int)
    for p in with_metrics:
        m = p.metrics
        if m is None:
            continue
        label = p.kind or "original"
        by_kind_views[label] += m.views or 0
        day = p.published_at.date().isoformat()
        by_day_views[day] += m.views or 0
        by_day_saves[day] += m.bookmarks or 0

    total_for_alloc = sum(by_kind_views.values())
    allocation = (
        [
            {
                "label": label,
                "pct": round(100 * amount / total_for_alloc, 1),
                "amount": amount,
            }
            for label, amount in sorted(by_kind_views.items(), key=lambda kv: -kv[1])
        ]
        if total_for_alloc
        else []
    )
    ranked = sorted(
        (p for p in with_metrics if p.metrics and p.metrics.views is not None),
        key=lambda p: p.metrics.views or 0 if p.metrics else 0,
        reverse=True,
    )
    top_posts = [
        {
            "id": p.id,
            "caption": p.text[:CAPTION_CHARS],
            "impressions": p.metrics.views if p.metrics else None,
            "likes": p.metrics.likes if p.metrics else None,
            "url": p.url,
        }
        for p in ranked[:TOP_POSTS]
    ]
    view_values = [
        p.metrics.views for p in ranked if p.metrics and p.metrics.views is not None
    ]
    return {
        "window_days": window_days,
        "posts_in_window": len(posts),
        "posts_with_metrics": len(with_metrics),
        "is_live_data": bool(with_metrics and views),
        "total_impressions": views,
        "total_likes": likes,
        "total_comments": comments,
        "total_shares": shares,
        "engagement_rate": engagement_rate,
        "median_impressions": median(view_values) if view_values else None,
        "allocation": allocation,
        "top_posts": top_posts,
        "reach_series": [
            {"date": d, "value": v} for d, v in sorted(by_day_views.items())
        ],
        "saves_series": [
            {"date": d, "value": v} for d, v in sorted(by_day_saves.items())
        ],
    }


def build(posts: PostStore, *, clock_now: Any = None) -> list[ToolSpec]:
    """``clock_now`` is a callable returning an aware datetime (injected so tests control time)."""

    def now() -> datetime:
        return clock_now() if clock_now else datetime.now(UTC)

    async def get_posts(ctx: ToolContext, limit: int = 20) -> dict[str, Any]:
        limit = max(1, min(int(limit), 100))
        rows = await posts.list_posts(ctx.profile_id, limit=limit)
        return {"posts": [_post_dict(p) for p in rows], "count": len(rows)}

    async def get_user_activity(
        ctx: ToolContext, kind: str = "all", limit: int = 15
    ) -> dict[str, Any]:
        limit = max(1, min(int(limit), 50))
        only = kind if kind in ("reply", "retweet") else None
        rows = await posts.list_activity(ctx.profile_id, kind=only, limit=limit)  # type: ignore[arg-type]
        return {"activity": [_activity_dict(a) for a in rows], "count": len(rows)}

    async def get_analytics(ctx: ToolContext) -> dict[str, Any]:
        since = now() - timedelta(days=ANALYTICS_WINDOW_DAYS)
        rows = await posts.list_posts(ctx.profile_id, since=since, limit=500)
        result = compute_analytics(rows, ANALYTICS_WINDOW_DAYS)
        result["profile_id"] = ctx.profile_id
        if not rows:
            result["note"] = (
                "No posts stored for this profile in the window. Nothing is estimated; "
                "run backfill_posts if an account is connected."
            )
        return result

    return [
        ToolSpec(
            name="get_posts",
            description="List recent posts tracked for a profile.",
            parameters={
                "type": "object",
                "properties": {
                    "profile_id": {"type": "integer"},
                    "limit": {"type": "integer", "default": 20},
                },
                "required": ["profile_id"],
            },
            handler=get_posts,
        ),
        ToolSpec(
            name="get_user_activity",
            description=(
                "Recent non-original activity for the profile: replies (the user's own words) "
                "and retweets (content they shared from others — NEVER attribute retweet text "
                "to the user). Use when you need deeper context on who the user is: e.g. "
                "connecting something to a recent opinion they expressed in replies "
                "('since you said X…'), or when they reference something they said outside "
                "their main posts. Replies reveal their thinking; retweets reveal their interests."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "profile_id": {"type": "integer"},
                    "kind": {
                        "type": "string",
                        "enum": ["reply", "retweet", "all"],
                        "default": "all",
                    },
                    "limit": {"type": "integer", "default": 15},
                },
                "required": ["profile_id"],
            },
            handler=get_user_activity,
        ),
        ToolSpec(
            name="get_analytics",
            description=(
                "Impressions, engagement statistics and content-format allocation computed from the "
                "profile's stored posts of the last 28 days. A metric the platform did not report is "
                "null, never zero. Use this whenever the user asks about their impressions, reach, "
                "analytics, metrics or performance."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "profile_id": {
                        "type": "integer",
                        "description": "Omit it — it defaults to the current chat profile.",
                    }
                },
            },
            handler=get_analytics,
        ),
    ]
