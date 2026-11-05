import logging
from datetime import UTC, datetime
from typing import Any

import neatlogs
from sqlmodel import select

from app.database import session_scope
from app.models.post import MetricSnapshot, Post
from app.models.profile import Profile
from app.schemas.niche import NicheConfig
from app.services.ingest import (
    finalize_ingest_pass,
    map_pfm_item,
    map_xpoz_item,
    pass_reached_window,
    store_raw_item,
)
from app.services.pfm import PFMClient
from app.services.xpoz import XpozClient

logger = logging.getLogger(__name__)

# Small limit for incremental refresh; full depth belongs to backfill_profile_posts
# (services/pfm.py paginates to NicheConfig.ORIGINALS_WINDOW).
INCREMENTAL_REFRESH_LIMIT = 20
XPOZ_MAX_PAGES = 8  # 20 posts/page -> covers the 100-original window with slack


def _window_bounds(published_times: list[datetime]) -> tuple[datetime, datetime] | None:
    if not published_times:
        return None
    return (min(published_times), max(published_times))


async def _ingest_pfm_feed(session, profile: Profile, profile_id: int) -> None:
    """Incremental refresh (one small page) from the profile's Post for Me feed.

    Every item goes through the shared ingest policy (app/services/ingest.py):
    NULL-preserving metrics, kind classification + self-reply routing, snapshot
    policy with age_hours, and end-of-pass bookkeeping (last_seen_at /
    deletion suspects / one profile_snapshots row / weak timezone inference).
    """
    if not profile.pfm_account_id:
        return
    client = PFMClient()
    pass_started = datetime.now(UTC)
    fetched_ids: set[str] = set()
    published_times: list[datetime] = []
    try:
        feed = await client.get_account_feed(profile.pfm_account_id, limit=INCREMENTAL_REFRESH_LIMIT)
        items = feed.get("data", feed) if isinstance(feed, dict) else feed
        if not isinstance(items, list):
            items = []
        for item in items:
            raw = map_pfm_item(item)
            if raw is None:
                continue
            result = await store_raw_item(session, profile, raw, source="pfm", now=pass_started)
            published_times.append(raw.published_at)
            if result.route == "post":
                fetched_ids.add(raw.platform_post_id)

        # One page: complete only if the page itself held everything, or the
        # fetched slice spans the 30d deletion window (bracket check in finalize).
        exhausted = len(items) < INCREMENTAL_REFRESH_LIMIT
        window = _window_bounds(published_times)
        await finalize_ingest_pass(
            session,
            profile,
            fetched_ids=fetched_ids,
            source="pfm",
            pass_started=pass_started,
            pass_complete=exhausted or pass_reached_window(window[0] if window else None, now=pass_started),
            fetched_window=window,
        )
        await session.commit()
    except Exception as exc:  # noqa: BLE001
        logger.debug("Analytics PFM backfill error for profile %s: %s", profile_id, exc)
    finally:
        await client.aclose()


async def _ingest_xpoz_user_posts(session, profile: Profile, profile_id: int) -> None:
    """Fallback: pull the user's own public posts via Xpoz, cursor-paged to the
    NicheConfig.ORIGINALS_WINDOW depth target (verified cursor pagination —
    docs/profile_extract_audit.md §Capabilities)."""
    if not profile.handle:
        return
    client = XpozClient()
    pass_started = datetime.now(UTC)
    fetched_ids: set[str] = set()
    published_times: list[datetime] = []
    cursor: str | None = None
    exhausted = False
    originals = 0
    pages = 0
    try:
        while pages < XPOZ_MAX_PAGES:
            results, next_cursor, has_more = await client.get_user_live_posts_page(
                profile.handle, cursor=cursor
            )
            pages += 1
            if not results:
                exhausted = True
                break
            for item in results:
                raw = map_xpoz_item(item)
                if raw is None:
                    continue
                result = await store_raw_item(session, profile, raw, source="xpoz", now=pass_started)
                published_times.append(raw.published_at)
                if result.route == "post":
                    fetched_ids.add(raw.platform_post_id)
                    originals += 1
            if not has_more or not next_cursor or next_cursor == cursor:
                exhausted = True
                break
            if originals >= NicheConfig.ORIGINALS_WINDOW:
                break  # depth target reached (incremental passes handle the rest)
            cursor = next_cursor

        window = _window_bounds(published_times)
        await finalize_ingest_pass(
            session,
            profile,
            fetched_ids=fetched_ids,
            source="xpoz",
            pass_started=pass_started,
            pass_complete=exhausted or pass_reached_window(window[0] if window else None, now=pass_started),
            fetched_window=window,
        )
        await session.commit()
    except Exception as exc:  # noqa: BLE001
        logger.debug("Analytics Xpoz fallback error for profile %s: %s", profile_id, exc)
    finally:
        await client.aclose()


@neatlogs.span(kind="CHAIN", name="get_profile_analytics")
async def get_profile_analytics(profile_id: int) -> dict[str, Any]:
    """Computes impression metrics, reach series, format allocation, and engagement

    for a profile, pulling live Post for Me feeds when available (Xpoz fallback).
    Never fabricates posts or metrics.
    """
    async with session_scope() as session:
        profile = await session.get(Profile, profile_id)
        if not profile:
            return {"error": f"Profile {profile_id} not found"}

        # Attempt PFM sync if profile has no posts yet
        existing_posts = (
            await session.exec(select(Post).where(Post.profile_id == profile_id))
        ).all()

        if not existing_posts and profile.pfm_account_id:
            await _ingest_pfm_feed(session, profile, profile_id)

        # Re-check after PFM; if still empty, fall back to Xpoz using the handle
        posts = (
            await session.exec(
                select(Post).where(Post.profile_id == profile_id).order_by(Post.published_at.desc())
            )
        ).all()
        if not posts and profile.handle:
            await _ingest_xpoz_user_posts(session, profile, profile_id)
            posts = (
                await session.exec(
                    select(Post).where(Post.profile_id == profile_id).order_by(Post.published_at.desc())
                )
            ).all()

        post_ids = [p.id for p in posts if p.id is not None]
        snapshots = []
        if post_ids:
            snapshots = (
                await session.exec(
                    select(MetricSnapshot).where(MetricSnapshot.post_id.in_(post_ids))
                )
            ).all()

    # NULL-safe: a missing metric is unknown (None) and contributes nothing —
    # it is never coerced into a fabricated total.
    total_views = sum(s.views or 0 for s in snapshots)
    total_likes = sum(s.likes or 0 for s in snapshots)
    total_comments = sum(s.comments or 0 for s in snapshots)
    total_shares = sum(s.shares or 0 for s in snapshots)

    is_live_data = len(posts) > 0 and total_views > 0

    if not is_live_data:
        # No real data yet. Never fabricate posts or metrics.
        return {
            "profile_id": profile_id,
            "handle": profile.handle,
            "name": profile.name,
            "total_impressions": 0,
            "total_likes": 0,
            "total_comments": 0,
            "total_shares": 0,
            "reach_change_pct": 0.0,
            "saves_change_pct": 0.0,
            "reach_series": [],
            "saves_series": [],
            "allocation": [],
            "top_posts": [],
            "is_live_data": False,
            "summary": (
                f"No post analytics found for @{profile.handle} yet. "
                "Data appears here after your posts are backfilled from Post for Me or Xpoz."
            ),
        }

    # If live data is available
    # Pair each post with its latest snapshot by post_id (never index-zip; snapshots can be unordered)
    latest_snap: dict[int, MetricSnapshot] = {}
    for s in snapshots:
        if s.post_id is None:
            continue
        prev = latest_snap.get(s.post_id)
        if prev is None or s.captured_at > prev.captured_at:
            latest_snap[s.post_id] = s

    paired = [(p, latest_snap[p.id]) for p in posts if p.id is not None and p.id in latest_snap]

    text_views = sum((s.views or 0) for p, s in paired if len(p.caption.split()) < 30)
    image_views = sum((s.views or 0) for p, s in paired if 30 <= len(p.caption.split()) < 80)
    other_views = max(0, total_views - text_views - image_views)

    # Real percentages only — a genuine 0% stays 0% (the old `or 40.0` fabricated a default).
    txt_pct = round((text_views / max(total_views, 1)) * 100, 1)
    img_pct = round((image_views / max(total_views, 1)) * 100, 1)
    vid_pct = round(100.0 - txt_pct - img_pct, 1)

    # Build trend series from real snapshot views only (no invented points)
    sorted_snaps = sorted(snapshots, key=lambda s: s.captured_at)
    views_list = [s.views or 0 for s in sorted_snaps]

    # Normalized delta series from real views; saves-track uses real likes deltas
    base_val = views_list[0] or 1
    reach_series = [round(((v - base_val) / base_val) * 100, 2) for v in views_list]
    likes_list = [s.likes or 0 for s in sorted_snaps]
    likes_base = likes_list[0] if likes_list and likes_list[0] else 1
    saves_series = [round(((lk - likes_base) / likes_base) * 100, 2) for lk in likes_list]

    # No invented change values — an empty series is 0.0, not a demo number.
    reach_change = reach_series[-1] if reach_series else 0.0
    saves_change = saves_series[-1] if saves_series else 0.0

    live_allocation = [
        {"name": "TXT", "label": "Text Posts", "pct": txt_pct, "amount": f"{text_views:,} views", "color": "#1d9bf0", "textColor": "var(--blue)"},
        {"name": "IMG", "label": "Image Cards", "pct": img_pct, "amount": f"{image_views:,} views", "color": "#f68f3c", "textColor": "var(--orange)"},
        {"name": "VID", "label": "Video / Rich", "pct": vid_pct, "amount": f"{other_views:,} views", "color": "rgba(255,255,255,0.28)", "textColor": "var(--text-dim)"},
    ]

    # Real top posts, correctly paired and sorted by impressions (NULL-safe keys)
    top_posts = [
        {"caption": p.caption[:120], "impressions": s.views or 0, "likes": s.likes or 0}
        for p, s in sorted(paired, key=lambda x: x[1].views or 0, reverse=True)[:3]
    ]

    return {
        "profile_id": profile_id,
        "handle": profile.handle,
        "name": profile.name,
        "total_impressions": total_views,
        "total_likes": total_likes,
        "total_comments": total_comments,
        "total_shares": total_shares,
        "reach_change_pct": reach_change,
        "saves_change_pct": saves_change,
        "reach_series": reach_series,
        "saves_series": saves_series,
        "allocation": live_allocation,
        "top_posts": top_posts,
        "is_live_data": True,
        "summary": (
            f"Your account @{profile.handle} generated {total_views:,} total impressions ({'+' if reach_change > 0 else ''}{reach_change}%). "
            f"Text posts account for {txt_pct}% of total views."
        ),
    }
