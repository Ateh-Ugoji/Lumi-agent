"""Post for Me (PFM) API client.

Endpoints and field names come from the provider's public OpenAPI document
(https://api.postforme.dev/docs/json, read 2026-10-27). Three facts matter most:

* ``permissions`` only accepts ``posts`` and ``feeds``. Without ``feeds`` the account feed and
  its metrics are never available, so :data:`PFM_PERMISSIONS` asks for both.
* The feed returns metrics only with ``expand=metrics``, and its paging data lives in
  ``meta`` (``cursor``, ``has_more``), not at the top level.
* ``GET /v1/social-accounts/{id}`` returns the platform ``access_token`` and ``refresh_token`` of the
  connected account. :class:`PfmAccount` drops them on purpose, so they can never reach a
  log, a response or the database by accident.

Nothing here runs a request at import time. The transport is injectable.
"""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import httpx

from ..config import ConnectionsConfig
from ..errors import ProviderRequestError, ProviderUnavailable, ValidationFailed
from ..http import ProviderHttp
from .limiter import Clock, Sleep, SlidingWindowLimiter

PROVIDER = "pfm"
BASE_URL = "https://api.postforme.dev"
HOSTS = frozenset({"api.postforme.dev"})
PFM_PERMISSIONS: tuple[str, ...] = ("posts", "feeds")
_VALID_PERMISSIONS = frozenset(PFM_PERMISSIONS)

# Local limits from the plan (5 requests per second, 40 per minute). The provider documents no
# limit in its OpenAPI file, so these are our own guard rails, not a verified quota.
DEFAULT_PER_SECOND = 5
DEFAULT_PER_MINUTE = 40
READ_RETRIES = 2
MAX_FEED_LIMIT = 100


@dataclass(frozen=True, slots=True)
class PfmAuthUrl:
    url: str
    platform: str


@dataclass(frozen=True, slots=True)
class PfmAccount:
    """A connected social account. Platform tokens are not part of this type."""

    id: str
    platform: str
    username: str | None
    user_id: str | None
    status: str
    external_id: str | None = None
    profile_photo_url: str | None = None

    @property
    def connected(self) -> bool:
        return self.status == "connected"


@dataclass(frozen=True, slots=True)
class PfmFeedPage:
    items: tuple[Mapping[str, Any], ...]
    cursor: str | None
    has_more: bool
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False)


def validate_permissions(permissions: Sequence[str]) -> tuple[str, ...]:
    """Return the permissions without duplicates, or fail when one is not ``posts``/``feeds``."""
    unique = tuple(dict.fromkeys(permissions))
    if not unique:
        raise ValidationFailed("permissions must not be empty", provider=PROVIDER)
    unknown = [p for p in unique if p not in _VALID_PERMISSIONS]
    if unknown:
        raise ValidationFailed("permissions must be posts and feeds", provider=PROVIDER)
    return unique


def _json_object(response: httpx.Response) -> dict[str, Any]:
    try:
        body = response.json()
    except ValueError:
        raise ProviderRequestError(
            "unexpected non-JSON answer", provider=PROVIDER
        ) from None
    if not isinstance(body, dict):
        raise ProviderRequestError("unexpected answer shape", provider=PROVIDER)
    return body


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def parse_account(body: Mapping[str, Any]) -> PfmAccount:
    account_id = _text(body.get("id"))
    if account_id is None:
        raise ProviderRequestError("account without id", provider=PROVIDER)
    return PfmAccount(
        id=account_id,
        platform=_text(body.get("platform")) or "",
        username=_text(body.get("username")),
        user_id=_text(body.get("user_id")),
        status=_text(body.get("status")) or "disconnected",
        external_id=_text(body.get("external_id")),
        profile_photo_url=_text(body.get("profile_photo_url")),
    )


class PfmClient:
    def __init__(
        self,
        config: ConnectionsConfig,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        limiter: SlidingWindowLimiter | None = None,
        clock: Clock = time.monotonic,
        sleep: Sleep | None = None,
    ) -> None:
        self._token = config.pfm_jwt_token
        kwargs: dict[str, Any] = {} if sleep is None else {"sleep": sleep}
        self._http = ProviderHttp(
            PROVIDER, allowed_hosts=HOSTS, transport=transport, timeout=10.0, **kwargs
        )
        self.limiter = limiter or SlidingWindowLimiter(
            per_second=DEFAULT_PER_SECOND,
            per_minute=DEFAULT_PER_MINUTE,
            provider=PROVIDER,
            clock=clock,
            **kwargs,
        )

    @property
    def configured(self) -> bool:
        return bool(self._token)

    async def _call(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json: Any = None,
        retries: int = 0,
    ) -> dict[str, Any]:
        if not self._token:
            raise ProviderUnavailable("PFM_JWT_TOKEN is not set", provider=PROVIDER)
        await self.limiter.acquire()
        response = await self._http.request(
            method,
            f"{BASE_URL}{path}",
            params=params,
            json=json,
            headers={"Authorization": f"Bearer {self._token}"},
            retries=retries,
        )
        return _json_object(response)

    async def create_auth_url(
        self,
        platform: str,
        external_id: str,
        permissions: Sequence[str] = PFM_PERMISSIONS,
    ) -> PfmAuthUrl:
        """Start the connect flow. ``permissions`` defaults to ``posts`` and ``feeds``."""
        if not platform or not external_id:
            raise ValidationFailed(
                "platform and external_id are required", provider=PROVIDER
            )
        body = await self._call(
            "POST",
            "/v1/social-accounts/auth-url",
            json={
                "platform": platform,
                "external_id": external_id,
                "permissions": list(validate_permissions(permissions)),
            },
        )
        url = _text(body.get("url"))
        if url is None:
            raise ProviderRequestError("auth url missing", provider=PROVIDER)
        return PfmAuthUrl(url=url, platform=_text(body.get("platform")) or platform)

    async def get_social_account(self, account_id: str) -> PfmAccount:
        if not account_id:
            raise ValidationFailed("account_id is required", provider=PROVIDER)
        body = await self._call(
            "GET", f"/v1/social-accounts/{account_id}", retries=READ_RETRIES
        )
        return parse_account(body)

    async def list_social_accounts(
        self, *, limit: int = 50, offset: int = 0, platform: str | None = None
    ) -> list[PfmAccount]:
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if platform:
            params["platform"] = platform
        body = await self._call(
            "GET", "/v1/social-accounts", params=params, retries=READ_RETRIES
        )
        data = body.get("data")
        if not isinstance(data, list):
            raise ProviderRequestError("accounts list missing", provider=PROVIDER)
        return [parse_account(item) for item in data if isinstance(item, dict)]

    async def get_account_feed_page(
        self,
        account_id: str,
        *,
        limit: int = 50,
        cursor: str | None = None,
        with_metrics: bool = True,
    ) -> PfmFeedPage:
        """One page of posts of a connected account, newest first, with metrics by default."""
        if not account_id:
            raise ValidationFailed("account_id is required", provider=PROVIDER)
        params: dict[str, Any] = {"limit": max(1, min(limit, MAX_FEED_LIMIT))}
        if cursor:
            params["cursor"] = cursor
        if with_metrics:
            params["expand"] = "metrics"
        body = await self._call(
            "GET",
            f"/v1/social-account-feeds/{account_id}",
            params=params,
            retries=READ_RETRIES,
        )
        data = body.get("data")
        if not isinstance(data, list):
            raise ProviderRequestError("feed data missing", provider=PROVIDER)
        meta = body.get("meta") if isinstance(body.get("meta"), dict) else {}
        next_cursor = _text(meta.get("cursor"))
        if "has_more" in meta:
            more = bool(meta["has_more"])
        else:
            more = meta.get("next") is not None
        has_more = more and next_cursor is not None
        return PfmFeedPage(
            items=tuple(item for item in data if isinstance(item, dict)),
            cursor=next_cursor,
            has_more=has_more,
            raw=body,
        )
