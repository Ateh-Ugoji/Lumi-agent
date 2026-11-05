"""Xpoz API client (third-party posts and user search).

Every call spends credits, so the client is built around three guards, in this order:

1. ``XPOZ_LIVE_ENABLED`` must be true, or ``LiveDisabled`` is raised before anything else.
2. The run budget (``XPOZ_RUN_CREDIT_BUDGET``, or ``XPOZ_RUN_CREDIT_BUDGET_<PLATFORM>`` when set) must have room for the price of the call, or
   ``BudgetExceeded`` is raised before any request leaves. A run therefore stops at the exact
   credit and never one call past it.
3. Keys rotate in order (``XPOZ_API_KEY``, then ``XPOZ_API_KEY_2``) when a key answers 401,
   402 or 403. A rotation inside one call is not charged twice.

Prices come from https://www.xpoz.ai/pricing (read 2026-10-27): X and Reddit 2 credits per
query, TikTok 5, Instagram 12, and the number of rows returned costs nothing. Endpoints and
field names come from https://api.xpoz.ai/openapi.json (same date). The credit price of a call
is not part of that file, and whether a failed call is billed is not documented, so the meter
keeps its charge even when a call fails (a ceiling, never an undercount).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

import httpx

from ..config import ConnectionsConfig
from ..errors import (
    BudgetExceeded,
    LiveDisabled,
    ProviderAuthError,
    ProviderRequestError,
    ProviderUnavailable,
    UnsupportedPlatform,
    ValidationFailed,
)
from ..http import ProviderHttp, raise_for_provider
from ..providers.base import utcnow
from .credits import CappedLedger, CreditEntry, CreditLedger, CreditMeter
from .limiter import Sleep

PROVIDER = "xpoz"
BASE_URL = "https://api.xpoz.ai"
HOSTS = frozenset({"api.xpoz.ai"})
READ_RETRIES = 1
_AUTH_STATUSES = (401, 402, 403)
_X_USERNAME = re.compile(r"^[A-Za-z0-9_]{1,15}$")

# Fields accepted by the user posts endpoint. ``isReply``, ``isQuote`` and ``mediaType`` do not
# exist; replies and quotes are derived from ``replyToTweetId`` and ``quotedTweetId``.
USER_LIVE_FIELDS = (
    "id,text,authorUsername,createdAt,likeCount,retweetCount,replyCount,impressionCount,"
    "quoteCount,bookmarkCount,lang,isRetweet,conversationId,quotedTweetId,"
    "replyToTweetId,replyToUserId,replyToUsername,hashtags,mentions,urls,mediaUrls"
)


@dataclass(frozen=True, slots=True)
class UserSearchSpec:
    """How to search users on one platform and how to read the rows."""

    path: str
    param: str  # query parameter name: "q" or "name"
    credits: int
    fields: str
    handle: str
    name: str | None
    avatar: str | None
    followers: str | None


USER_SEARCH: Mapping[str, UserSearchSpec] = {
    "x": UserSearchSpec(
        "/api/data/twitter/users/live",
        "q",
        2,
        "username,name,profileImageUrl,followersCount",
        "username",
        "name",
        "profileImageUrl",
        "followersCount",
    ),
    "instagram": UserSearchSpec(
        "/api/data/instagram/users/live",
        "name",
        12,
        "username,fullName,profilePicUrl,followerCount",
        "username",
        "fullName",
        "profilePicUrl",
        "followerCount",
    ),
    "tiktok": UserSearchSpec(
        "/api/data/tiktok/users/live",
        "name",
        5,
        "username,nickname,avatar,followerCount",
        "username",
        "nickname",
        "avatar",
        "followerCount",
    ),
    # Reddit has no display name and no follower count. Karma is not followers.
    "reddit": UserSearchSpec(
        "/api/data/reddit/users/live",
        "q",
        2,
        "username,profilePicUrl",
        "username",
        None,
        "profilePicUrl",
        None,
    ),
}
# Instagram, TikTok and Reddit post rows carry their own field names; the mapper reads these.
IG_POST_FIELDS = (
    "id,username,caption,createdAt,likeCount,commentCount,videoPlayCount,mediaType,"
    "codeUrl,profilePicUrl"
)
TT_POST_FIELDS = (
    "id,username,description,createdAt,likeCount,commentCount,playCount,forwardCount,"
    "videoThumbnail"
)
RD_POST_FIELDS = (
    "id,title,selftext,permalink,postUrl,authorUsername,subredditName,score,commentsCount,"
    "createdAt,thumbnail"
)


@dataclass(frozen=True, slots=True)
class PostEndpoint:
    """The two post endpoints of one platform and what one page costs."""

    search_path: str
    user_path: str
    fields: str
    credits: int


# Prices from https://www.xpoz.ai/pricing: X and Reddit 2 credits per query, TikTok 5, Instagram 12.
POST_ENDPOINTS: Mapping[str, PostEndpoint] = {
    "x": PostEndpoint(
        "/api/data/twitter/posts/live",
        "/api/data/twitter/posts/users/{username}/live",
        USER_LIVE_FIELDS,
        2,
    ),
    "instagram": PostEndpoint(
        "/api/data/instagram/posts/live",
        "/api/data/instagram/posts/users/{identifier}/live",
        IG_POST_FIELDS,
        12,
    ),
    "tiktok": PostEndpoint(
        "/api/data/tiktok/posts/live",
        "/api/data/tiktok/posts/users/{identifier}/live",
        TT_POST_FIELDS,
        5,
    ),
    "reddit": PostEndpoint(
        "/api/data/reddit/posts/live",
        "/api/data/reddit/posts/users/{username}/live",
        RD_POST_FIELDS,
        2,
    ),
}
# X is the only platform whose timeline endpoint accepts ``since``; the rest are filtered after.
_SINCE_PLATFORMS = frozenset({"x"})
_USERNAME = {
    "x": _X_USERNAME,
    "instagram": re.compile(r"^[A-Za-z0-9._]{1,30}$"),
    "tiktok": re.compile(r"^[A-Za-z0-9._]{1,24}$"),
    "reddit": re.compile(r"^[A-Za-z0-9_-]{3,20}$"),
}

def post_credits(platform: str) -> int:
    """Price of one post page, or ``UnsupportedPlatform`` when Xpoz has no post endpoint."""
    spec = POST_ENDPOINTS.get(platform)
    if spec is None:
        raise UnsupportedPlatform(
            f"Xpoz has no post search for {platform}", provider=PROVIDER
        )
    return spec.credits


def user_search_credits(platform: str) -> int:
    """Price of one user search, or ``UnsupportedPlatform`` when Xpoz has no endpoint."""
    spec = USER_SEARCH.get(platform)
    if spec is None:
        raise UnsupportedPlatform(
            f"Xpoz has no user search for {platform}", provider=PROVIDER
        )
    return spec.credits


@dataclass(frozen=True, slots=True)
class XpozPage:
    results: tuple[Mapping[str, Any], ...]
    next_cursor: str | None
    has_more: bool
    credits: int = 0
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False)


def _parse_page(body: Any, credits: int) -> XpozPage:
    if not isinstance(body, dict):
        raise ProviderRequestError("unexpected answer shape", provider=PROVIDER)
    results = body.get("results")
    if results is None:
        results = []
    if not isinstance(results, list):
        raise ProviderRequestError("results is not a list", provider=PROVIDER)
    cursor = body.get("next_page_cursor")
    cursor = cursor if isinstance(cursor, str) and cursor else None
    return XpozPage(
        results=tuple(r for r in results if isinstance(r, dict)),
        next_cursor=cursor,
        has_more=bool(body.get("has_more")) and cursor is not None,
        credits=credits,
        raw=body,
    )


class XpozClient:
    def __init__(
        self,
        config: ConnectionsConfig,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        meter: CreditMeter | None = None,
        ledger: CreditLedger | None = None,
        run_id: str | None = None,
        clock: Callable[[], datetime] = utcnow,
        sleep: Sleep | None = None,
    ) -> None:
        self._live = config.xpoz_live_enabled
        self._keys = config.xpoz_api_keys
        self._dead_slots: set[int] = set()
        self.meter = meter or CreditMeter(
            config.xpoz_run_credit_budget, provider=PROVIDER
        )
        # A platform with its own budget (XPOZ_RUN_CREDIT_BUDGET_<PLATFORM>) is metered apart.
        self._platform_meters = {
            platform: CreditMeter(budget, provider=PROVIDER)
            for platform, budget in config.xpoz_platform_budgets.items()
        }
        self._ledger = ledger
        self._run_id = run_id
        self._clock = clock
        kwargs: dict[str, Any] = {} if sleep is None else {"sleep": sleep}
        self._http = ProviderHttp(
            PROVIDER, allowed_hosts=HOSTS, transport=transport, timeout=15.0, **kwargs
        )

    @property
    def live_enabled(self) -> bool:
        return self._live

    def _live_slots(self) -> list[int]:
        return [i for i in range(1, len(self._keys) + 1) if i not in self._dead_slots]

    def meter_for(self, platform: str) -> CreditMeter:
        return self._platform_meters.get(platform, self.meter)

    async def _get(
        self,
        route: str,
        path: str,
        params: Mapping[str, Any],
        credits: int,
        platform: str = "x",
    ) -> XpozPage:
        if not self._live:
            raise LiveDisabled("XPOZ_LIVE_ENABLED is false", provider=PROVIDER)
        if not self._keys:
            raise ProviderUnavailable("XPOZ_API_KEY is not set", provider=PROVIDER)
        slots = self._live_slots()
        if not slots:
            raise ProviderAuthError(
                "every Xpoz key was rejected in this run", provider=PROVIDER
            )
        meter = self.meter_for(platform)
        if isinstance(self._ledger, CappedLedger):
            # The meter lives and dies with this client. The cap reads what was really spent.
            await self._ledger.ensure_room(credits)
        meter.charge(credits)  # raises BudgetExceeded before any request is sent
        refusals: list[int] = []
        for slot in slots:
            response = await self._http.request(
                "GET",
                f"{BASE_URL}{path}",
                params=params,
                headers={"Authorization": f"Bearer {self._keys[slot - 1]}"},
                retries=READ_RETRIES,
                check=False,
            )
            if response.status_code in _AUTH_STATUSES:
                self._dead_slots.add(slot)
                refusals.append(response.status_code)
                continue
            raise_for_provider(response, PROVIDER)
            try:
                body = response.json()
            except ValueError:
                raise ProviderRequestError(
                    "unexpected non-JSON answer", provider=PROVIDER
                ) from None
            page = _parse_page(body, credits)
            if self._ledger is not None:
                await self._ledger.record(
                    CreditEntry(
                        provider=PROVIDER,
                        route=route,
                        credits=credits,
                        key_slot=slot,
                        at=self._clock(),
                        run_id=self._run_id,
                    )
                )
            return page
        if refusals and all(code == 402 for code in refusals):
            raise BudgetExceeded(
                "Xpoz reports no credits left on any key",
                provider=PROVIDER,
                spent=meter.spent,
                budget=meter.budget,
            )
        raise ProviderAuthError(
            f"Xpoz rejected every key ({', '.join(str(c) for c in refusals)})",
            provider=PROVIDER,
        )

    async def user_posts_page(
        self,
        platform: str,
        username: str,
        *,
        cursor: str | None = None,
        since: date | datetime | None = None,
    ) -> XpozPage:
        """One page of a public account's posts, newest first (2, 12, 5 or 2 credits for
        x, instagram, tiktok and reddit). ``since`` is only sent on X; see ``_SINCE_PLATFORMS``."""
        spec = POST_ENDPOINTS.get(platform)
        if spec is None:
            raise UnsupportedPlatform(
                f"Xpoz has no user timeline for {platform}", provider=PROVIDER
            )
        clean = username.strip().lstrip("@")
        pattern = _USERNAME[platform]
        if not pattern.match(clean):
            raise ValidationFailed(f"invalid {platform} username", provider=PROVIDER)
        params: dict[str, Any] = {"fields": spec.fields}
        if cursor:
            params["cursor"] = cursor
        if since is not None and platform in _SINCE_PLATFORMS:
            params["since"] = (
                since.date() if isinstance(since, datetime) else since
            ).isoformat()
        return await self._get(
            f"{platform}.posts.user",
            spec.user_path.format(username=clean, identifier=clean),
            params,
            spec.credits,
            platform,
        )

    async def search_posts(
        self, platform: str, query: str, *, cursor: str | None = None
    ) -> XpozPage:
        """One page of public posts matching a keyword query (2, 12, 5 or 2 credits for
        x, instagram, tiktok and reddit). Facebook and LinkedIn have no such endpoint."""
        spec = POST_ENDPOINTS.get(platform)
        if spec is None:
            raise UnsupportedPlatform(
                f"Xpoz has no post search for {platform}", provider=PROVIDER
            )
        if not query.strip():
            raise ValidationFailed("query must not be blank", provider=PROVIDER)
        params: dict[str, Any] = {"q": query.strip(), "fields": spec.fields}
        if cursor:
            params["cursor"] = cursor
        return await self._get(
            f"{platform}.posts.search", spec.search_path, params, spec.credits, platform
        )

    async def search_users(
        self, platform: str, query: str, *, cursor: str | None = None
    ) -> XpozPage:
        """One page of accounts on ``platform`` (2, 12, 5 or 2 credits for x, instagram, tiktok, reddit)."""
        spec = USER_SEARCH.get(platform)
        if spec is None:
            raise UnsupportedPlatform(
                f"Xpoz has no user search for {platform}", provider=PROVIDER
            )
        text = query.strip().lstrip("@")
        if not text:
            raise ValidationFailed("query must not be blank", provider=PROVIDER)
        params: dict[str, Any] = {spec.param: text, "fields": spec.fields}
        if cursor:
            params["cursor"] = cursor
        return await self._get(
            f"{platform}.users.search", spec.path, params, spec.credits, platform
        )
