"""Post for Me API client.

Confirmed against the real OpenAPI spec (https://api.postforme.dev/docs/json) —
see .agents/external-services.md for the full endpoint picture and field mappings.

Classification/routing/snapshot policy lives in app.services.ingest (shared by
all three own-post paths); this module re-exports the helpers its importers
know (tools/voice, tests/test_post_filter) so existing call sites keep working.
"""

import logging
from datetime import UTC, datetime

import httpx

from app.config import get_settings
from app.models.profile import Profile
from app.schemas.niche import NicheConfig
from app.services.ingest import (
    classify_post_kind,
    finalize_ingest_pass,
    is_authentic_original,
    map_pfm_item,
    pass_reached_window,
    store_raw_item,
    upsert_user_activity,
)

log = logging.getLogger(__name__)

BASE_URL = "https://api.postforme.dev"

__all__ = [
    "MAX_BACKFILL_PAGES",
    "PFMClient",
    "backfill_profile_posts",
    "classify_post_kind",
    "is_authentic_original",
    "upsert_user_activity",
]


class PFMClient:
    def __init__(self) -> None:
        settings = get_settings()
        self._client = httpx.AsyncClient(
            base_url=BASE_URL,
            headers={"Authorization": f"Bearer {settings.pfm_jwt_token}"},
            timeout=httpx.Timeout(10.0, connect=5.0),
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def create_auth_url(self, platform: str, external_id: str, permissions: list[str]) -> dict:
        """Starts the OAuth connect flow. Returns {"url": ..., "platform": ...} to redirect the user to."""
        response = await self._client.post(
            "/v1/social-accounts/auth-url",
            json={"platform": platform, "external_id": external_id, "permissions": permissions},
        )
        response.raise_for_status()
        return response.json()

    async def get_social_account(self, account_id: str) -> dict:
        response = await self._client.get(f"/v1/social-accounts/{account_id}")
        response.raise_for_status()
        return response.json()

    async def get_account_feed(self, social_account_id: str, limit: int = 50, cursor: str | None = None) -> dict:
        """Paginated post history for a connected account. Each item carries both `caption` and `metrics`."""
        params = {"limit": limit}
        if cursor:
            params["cursor"] = cursor
        response = await self._client.get(f"/v1/social-account-feeds/{social_account_id}", params=params)
        response.raise_for_status()
        return response.json()


MAX_BACKFILL_PAGES = 50


async def backfill_profile_posts(session, profile_id: int, pfm_account_id: str) -> dict:
    """Fetch posts+metrics from PFM and upsert via the shared ingest policy.

    Depth target (Step 2): paginate until NicheConfig.ORIGINALS_WINDOW originals
    or the source is exhausted (MAX_BACKFILL_PAGES cap). Small limits belong to
    the incremental refresh paths (analytics). Records age_hours on snapshots,
    routes replies/RTs to user_activity, self-replies to posts, and ends the
    pass with last_seen/deletion/profile-snapshot bookkeeping.
    """
    settings = get_settings()
    if not settings.pfm_jwt_token:
        log.warning("Skipping PFM backfill for profile %s: PFM_JWT_TOKEN not configured", profile_id)
        return {"profile_id": profile_id, "new_posts": 0, "updated_posts": 0, "skipped": "no_pfm_token"}

    profile = await session.get(Profile, profile_id)
    if profile is None:
        return {"profile_id": profile_id, "error": "profile not found"}

    client = PFMClient()
    new_count = 0
    updated_count = 0
    activity_count = 0
    originals = 0
    cursor: str | None = None
    pages = 0
    exhausted = False
    rate_limited = False
    fetched_ids: set[str] = set()
    published_times: list[datetime] = []
    pass_started = datetime.now(UTC)

    try:
        while pages < MAX_BACKFILL_PAGES:
            data = await client.get_account_feed(pfm_account_id, limit=50, cursor=cursor)
            items = data.get("data") or data.get("items") or []
            if not items:
                exhausted = True
                break

            for item in items:
                raw = map_pfm_item(item)
                if raw is None:
                    continue
                result = await store_raw_item(session, profile, raw, source="pfm", now=pass_started)
                published_times.append(raw.published_at)
                if result.route == "post":
                    fetched_ids.add(raw.platform_post_id)
                    originals += 1
                    if result.created:
                        new_count += 1
                    else:
                        updated_count += 1
                elif result.route == "activity":
                    activity_count += 1

            pages += 1
            await session.commit()  # keep per-page progress (pre-existing behavior)

            cursor = data.get("cursor") or data.get("next_cursor")
            if not cursor:
                exhausted = True
                break
            if originals >= NicheConfig.ORIGINALS_WINDOW:
                break  # depth target reached

    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 429:
            log.warning("PFM rate limited during backfill for profile %s, will retry next cycle", profile_id)
            rate_limited = True
        else:
            raise
    finally:
        await client.aclose()

    oldest = min(published_times) if published_times else None
    newest = max(published_times) if published_times else None
    # complete = source exhausted OR the fetched slice spans the 30d window
    pass_complete = exhausted or pass_reached_window(oldest, now=pass_started)
    bookkeeping = await finalize_ingest_pass(
        session,
        profile,
        fetched_ids=fetched_ids,
        source="pfm",
        pass_started=pass_started,
        pass_complete=pass_complete,
        fetched_window=(oldest, newest) if oldest is not None and newest is not None else None,
    )
    await session.commit()

    return {
        "profile_id": profile_id,
        "new_posts": new_count,
        "updated_posts": updated_count,
        "new_activity": activity_count,
        "originals_fetched": len(fetched_ids),
        "pass_complete": pass_complete,
        "bookkeeping": bookkeeping,
        **({"rate_limited": True} if rate_limited else {}),
    }
