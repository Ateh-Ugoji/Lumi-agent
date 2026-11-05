"""``HandleLive`` backed by Xpoz user search."""

from __future__ import annotations

from typing import Any

from ..clients.xpoz import USER_SEARCH, UserSearchSpec, XpozClient
from .ranking import clean_followers
from .types import HandleRow


def row_from_user(
    platform: str, spec: UserSearchSpec, user: dict[str, Any]
) -> HandleRow | None:
    raw = user.get(spec.handle)
    if not isinstance(raw, str) or not raw.strip():
        return None
    name = user.get(spec.name) if spec.name else None
    avatar = user.get(spec.avatar) if spec.avatar else None
    return HandleRow(
        handle=raw.strip().lstrip("@"),
        platform=platform,
        display_name=name if isinstance(name, str) else "",
        avatar_url=avatar if isinstance(avatar, str) else "",
        followers=clean_followers(user.get(spec.followers)) if spec.followers else None,
        source="live",
    )


class XpozHandleLive:
    def __init__(self, client: XpozClient) -> None:
        self._client = client

    def supports(self, platform: str) -> bool:
        return platform in USER_SEARCH

    async def search(self, platform: str, query: str) -> list[HandleRow]:
        spec = USER_SEARCH[platform]
        page = await self._client.search_users(platform, query)
        rows = (row_from_user(platform, spec, dict(u)) for u in page.results)
        return [r for r in rows if r is not None]


class XpozExactUser:
    """``ExactUserLookup``: one paid user search, kept only if the username matches exactly."""

    def __init__(self, live: XpozHandleLive) -> None:
        self._live = live

    async def exact(self, platform: str, handle: str) -> HandleRow | None:
        if not self._live.supports(platform):
            return None
        target = handle.strip().lstrip("@").lower()
        for row in await self._live.search(platform, handle):
            if row.handle.lower() == target:
                return row
        return None  # the top hit of a fuzzy search is another person
