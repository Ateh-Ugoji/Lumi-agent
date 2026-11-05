"""``SocialData`` port (``lumi_ai.ports``) backed by Xpoz.

Coverage is what Xpoz offers, no more:

* ``x``, ``instagram`` and ``tiktok``: user posts, keyword search, user search and lookup.
* ``linkedin`` and ``facebook``: ``UnsupportedPlatform``; Xpoz has no post endpoint for either,
  and publishing-side APIs (Meta Graph, LinkedIn) are what serve those networks instead.
  Reddit has post endpoints too, but it is not part of the port's platform list.

``fetch_user_posts`` pages 20 rows at a time (2, 12 and 5 credits per page for x, instagram
and tiktok). When the run budget runs out after some posts were read, the posts already paid
for are returned instead of being thrown away. With nothing read yet, ``BudgetExceeded`` is
raised. Keep ``XPOZ_RUN_CREDIT_BUDGET`` at or above 12 or an Instagram page never fits.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, cast

from lumi_ai.ports import Platform, PostIn, UserInfo

from .clients.xpoz import USER_SEARCH, XpozClient, XpozPage
from .errors import BudgetExceeded, UnsupportedPlatform
from .ingest import map_xpoz_platform_post, parse_datetime

PROVIDER = "xpoz"
MAX_PAGES = 10  # hard stop against a cursor loop: 10 pages = 20 credits on X, 120 on Instagram
_USER_PLATFORMS = ("x", "instagram", "tiktok")
_POST_PLATFORMS = ("x", "instagram", "tiktok")


def _unsupported(platform: str, what: str) -> UnsupportedPlatform:
    return UnsupportedPlatform(
        f"{what} is not available for {platform}", provider=PROVIDER
    )


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def _count(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def map_user(platform: str, row: Mapping[str, Any]) -> UserInfo | None:
    """Map one Xpoz user row using the per-platform field names. ``None`` without a handle."""
    spec = USER_SEARCH[platform]
    raw = row.get(spec.handle)
    if not isinstance(raw, str) or not raw.strip():
        return None
    handle = raw.strip().lstrip("@")
    name = row.get(spec.name) if spec.name else None
    followers = _count(row.get(spec.followers)) if spec.followers else None
    return UserInfo(
        platform=cast(Platform, platform),
        handle=handle,
        display_name=name if isinstance(name, str) and name else None,
        followers=followers,
    )


class XpozSocialData:
    def __init__(self, client: XpozClient) -> None:
        self._client = client

    async def fetch_user_posts(
        self, platform: Platform, handle: str, since: datetime | None, limit: int
    ) -> list[PostIn]:
        if platform not in _POST_PLATFORMS:
            raise _unsupported(platform, "reading user posts")
        if limit <= 0:
            return []
        floor = _aware(since)
        posts: list[PostIn] = []
        cursor: str | None = None
        for _ in range(MAX_PAGES):
            try:
                page: XpozPage = await self._client.user_posts_page(
                    platform, handle, cursor=cursor, since=floor
                )
            except BudgetExceeded:
                if posts:
                    break
                raise
            reached_old = False
            for row in page.results:
                published = parse_datetime(row.get("createdAt"))
                if floor is not None and published is not None and published < floor:
                    reached_old = True
                    continue
                post = map_xpoz_platform_post(platform, row, user_handle=handle)
                if post is not None:
                    posts.append(post)
            if len(posts) >= limit or reached_old or not page.has_more:
                break
            cursor = page.next_cursor
        posts.sort(key=lambda p: p.published_at, reverse=True)
        return posts[: max(limit, 0)]

    async def search_posts(
        self, platform: Platform, query: str, limit: int
    ) -> list[PostIn]:
        if platform not in _POST_PLATFORMS:
            raise _unsupported(
                platform, f"keyword search (Xpoz has no {platform} post search)"
            )
        if limit <= 0:
            return []
        posts: list[PostIn] = []
        cursor: str | None = None
        for _ in range(MAX_PAGES):
            try:
                page = await self._client.search_posts(platform, query, cursor=cursor)
            except BudgetExceeded:
                if posts:
                    break
                raise
            for row in page.results:
                post = map_xpoz_platform_post(platform, row)
                if post is not None:
                    posts.append(post)
            if len(posts) >= limit or not page.has_more:
                break
            cursor = page.next_cursor
        return posts[: max(limit, 0)]

    async def search_users(
        self, platform: Platform, query: str, limit: int
    ) -> list[UserInfo]:
        if platform not in _USER_PLATFORMS:
            raise _unsupported(platform, "user search")
        if limit <= 0:
            return []
        page = await self._client.search_users(platform, query)
        users = [u for row in page.results if (u := map_user(platform, row))]
        return users[: max(limit, 0)]

    async def get_user(self, platform: Platform, handle: str) -> UserInfo | None:
        """Exact, case-insensitive handle match inside one user search. Costs one search."""
        wanted = handle.strip().lstrip("@").lower()
        for user in await self.search_users(platform, wanted, 20):
            if user.handle.lower() == wanted:
                return user
        return None
