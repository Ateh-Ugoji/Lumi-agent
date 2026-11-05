"""The ``SocialProvider`` contract and the value objects that cross it.

Token fields are excluded from ``repr`` so a stray log line or traceback cannot leak them.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import httpx

from lumi_ai.generation.enforcement import hashtags
from lumi_ai.generation.platforms import measure, rules_for
from lumi_ai.ports import PostIn, PostMetrics

from ..errors import ProviderUnavailable, UnsupportedOperation, ValidationFailed
from ..http import ProviderHttp

AccountStatus = Literal["active", "limited"]


def utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class TokenSet:
    access_token: str = field(repr=False)
    refresh_token: str | None = field(default=None, repr=False)
    expires_at: datetime | None = None
    scopes: tuple[str, ...] = ()
    token_type: str = "Bearer"

    def expires_within(self, delta: timedelta, *, now: datetime | None = None) -> bool:
        if self.expires_at is None:
            return False
        return self.expires_at - (now or datetime.now(UTC)) <= delta


@dataclass(frozen=True, slots=True)
class AuthorizationRequest:
    url: str
    state: str


@dataclass(frozen=True, slots=True)
class AccountInfo:
    """One connectable identity: a profile, or a Facebook Page."""

    external_id: str
    display_name: str
    handle: str | None = None
    status: AccountStatus = "active"
    # Facebook Pages carry their own token, separate from the user token.
    access_token: str | None = field(default=None, repr=False)
    note: str | None = None


@dataclass(frozen=True, slots=True)
class Capabilities:
    can_publish: bool
    can_read_posts: bool
    can_read_metrics: bool
    uses_pkce: bool
    supports_refresh: bool
    max_text_length: int
    scopes: tuple[str, ...]
    paid: bool = False


@dataclass(frozen=True, slots=True)
class PublishDraft:
    text: str
    link: str | None = None


@dataclass(frozen=True, slots=True)
class PublishResult:
    external_post_id: str | None
    url: str | None
    dry_run: bool
    # Extra information for the confirmation screen, such as the estimated cost on X.
    estimated_cost_usd: float | None = None
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RevokeOutcome:
    remote_revoked: bool
    reason: str | None = None


def seconds_to_expiry(expires_in: Any, *, now: datetime) -> datetime | None:
    try:
        seconds = float(expires_in)
    except (TypeError, ValueError):
        return None
    return now + timedelta(seconds=seconds)


def split_scopes(raw: Any) -> tuple[str, ...]:
    if not isinstance(raw, str):
        return ()
    return tuple(s for s in raw.replace(",", " ").split() if s)


class SocialProvider(ABC):
    """Contract shared by ``meta``, ``linkedin``, ``x`` and ``pfm``.

    ``name`` is the provider id used in URLs and in the database. ``platform`` is the
    ``lumi_ai.ports.Platform`` the data belongs to.
    """

    name: str
    platform: str

    def __init__(
        self, http: ProviderHttp, *, clock: Callable[[], datetime] = utcnow
    ) -> None:
        self._http = http
        self._clock = clock

    @abstractmethod
    def capabilities(self) -> Capabilities: ...

    @abstractmethod
    def build_authorize_url(
        self, *, state: str, redirect_uri: str, code_challenge: str | None = None
    ) -> AuthorizationRequest:
        """Pure local computation. Never touches the network."""

    @abstractmethod
    async def exchange_code(
        self, *, code: str, redirect_uri: str, code_verifier: str | None = None
    ) -> TokenSet: ...

    async def refresh(self, tokens: TokenSet) -> TokenSet:
        raise UnsupportedOperation(
            f"{self.name} cannot refresh tokens", provider=self.name
        )

    @abstractmethod
    async def revoke(self, tokens: TokenSet) -> RevokeOutcome: ...

    @abstractmethod
    async def get_account(self, tokens: TokenSet) -> AccountInfo: ...

    async def list_accounts(self, tokens: TokenSet) -> list[AccountInfo]:
        return [await self.get_account(tokens)]

    async def fetch_posts(
        self, tokens: TokenSet, account: AccountInfo, *, limit: int = 20
    ) -> list[PostIn]:
        raise UnsupportedOperation(
            f"{self.name} does not read posts", provider=self.name
        )

    async def fetch_metrics(
        self, tokens: TokenSet, account: AccountInfo, post_id: str
    ) -> PostMetrics:
        raise UnsupportedOperation(
            f"{self.name} does not read metrics", provider=self.name
        )

    @abstractmethod
    async def publish(
        self,
        tokens: TokenSet,
        account: AccountInfo,
        draft: PublishDraft,
        *,
        dry_run: bool = False,
    ) -> PublishResult: ...

    @property
    def text_limit(self) -> int:
        """The network's hard limit, from ``lumi_ai.generation.platforms`` (one source)."""
        return rules_for(self.platform).hard_limit

    def validate_draft(self, draft: PublishDraft) -> None:
        """Reject a draft the network would reject, using the same rules the generator uses.

        Length is measured the way the network counts it (TikTok counts UTF-16 units). Facebook's
        limit is not official, so it is a ceiling and not a promise.
        """
        text = draft.text.strip()
        if not text:
            raise ValidationFailed("the post is empty", provider=self.name)
        rules = rules_for(self.platform)
        length = measure(self.platform, draft.text)
        if length > rules.hard_limit:
            raise ValidationFailed(
                f"the post has {length} characters and {rules.label} allows {rules.hard_limit}",
                provider=self.name,
            )
        if rules.hashtag_cap_enforced:
            found = len(hashtags(draft.text))
            if found > rules.hashtags_max:
                raise ValidationFailed(
                    f"the post has {found} hashtags and {rules.label} accepts at most "
                    f"{rules.hashtags_max}",
                    provider=self.name,
                )


def bearer(tokens: TokenSet) -> dict[str, str]:
    return {"Authorization": f"Bearer {tokens.access_token}"}


def json_object(response: httpx.Response, provider: str) -> dict[str, Any]:
    try:
        body = response.json()
    except ValueError:
        body = None
    if not isinstance(body, dict):
        raise ProviderUnavailable("unexpected response shape", provider=provider)
    return body
