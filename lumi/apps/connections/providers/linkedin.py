"""LinkedIn adapter for member profiles (Share on LinkedIn).

Self-service apps get ``openid profile email`` and ``w_member_social``: Lumi can publish to
the member's own profile. Reading posts needs ``r_member_social``, which LinkedIn restricts to
approved apps, so without it the account is marked ``limited`` and reads raise
``UnsupportedPlatform``. Tokens last 60 days and cannot be refreshed unless the app is an
approved partner, so ``refresh`` only works when a refresh token exists.

The ``Linkedin-Version`` header comes from ``LINKEDIN_API_VERSION``. Version 202511 sunsets on
2026-11-16.

Sources, checked 2026-10-27:
https://learn.microsoft.com/en-us/linkedin/shared/authentication/authorization-code-flow
https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/posts-api?view=li-lms-2026-09
https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/little-text-format?view=li-lms-2026-09
Not confirmed in those pages: the revoke endpoint, ``/v2/userinfo``, the 3,000 character
limit, and the response shape of the read-posts call.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode

from lumi_ai.ports import PostIn

from ..config import ConnectionsConfig
from ..errors import ProviderAuthError, ProviderUnavailable, UnsupportedPlatform
from ..http import ProviderHttp
from .base import (
    AccountInfo,
    AuthorizationRequest,
    Capabilities,
    PublishDraft,
    PublishResult,
    RevokeOutcome,
    SocialProvider,
    TokenSet,
    bearer,
    json_object,
    seconds_to_expiry,
    split_scopes,
)

AUTHORIZE_URL = "https://www.linkedin.com/oauth/v2/authorization"
TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
REVOKE_URL = "https://www.linkedin.com/oauth/v2/revoke"
API_BASE = "https://api.linkedin.com"
HOSTS = frozenset({"www.linkedin.com", "api.linkedin.com"})
SCOPES = ("openid", "profile", "email", "w_member_social")
READ_SCOPE = "r_member_social"
MAX_TEXT = 3000

# Characters reserved by LinkedIn's "little" text format. An unescaped one is parsed as markup
# and can swallow or truncate the post.
_RESERVED = re.compile(r"([\\|{}@\[\]()<>#*_~])")


def escape_commentary(text: str) -> str:
    return _RESERVED.sub(r"\\\1", text)


class LinkedInProvider(SocialProvider):
    name = "linkedin"
    platform = "linkedin"

    def __init__(
        self, http: ProviderHttp, config: ConnectionsConfig, **kwargs: Any
    ) -> None:
        super().__init__(http, **kwargs)
        self._config = config

    def _require_credentials(self) -> tuple[str, str]:
        if not (
            self._config.linkedin_client_id and self._config.linkedin_client_secret
        ):
            raise ProviderUnavailable(
                "LINKEDIN_CLIENT_ID and LINKEDIN_CLIENT_SECRET are not set",
                provider=self.name,
            )
        return self._config.linkedin_client_id, self._config.linkedin_client_secret

    def _api_headers(self, tokens: TokenSet) -> dict[str, str]:
        return {
            **bearer(tokens),
            "Linkedin-Version": self._config.linkedin_api_version,
            "X-Restli-Protocol-Version": "2.0.0",
        }

    def capabilities(self) -> Capabilities:
        return Capabilities(
            can_publish=True,
            can_read_posts=False,  # only with r_member_social, decided per account
            can_read_metrics=False,
            uses_pkce=False,
            supports_refresh=False,
            max_text_length=MAX_TEXT,
            scopes=SCOPES,
        )

    def build_authorize_url(
        self, *, state: str, redirect_uri: str, code_challenge: str | None = None
    ) -> AuthorizationRequest:
        if not self._config.linkedin_client_id:
            raise ProviderUnavailable(
                "LINKEDIN_CLIENT_ID is not set", provider=self.name
            )
        query = urlencode(
            {
                "response_type": "code",
                "client_id": self._config.linkedin_client_id,
                "redirect_uri": redirect_uri,
                "state": state,
                "scope": " ".join(SCOPES),
            }
        )
        return AuthorizationRequest(url=f"{AUTHORIZE_URL}?{query}", state=state)

    def _tokens(
        self, body: dict[str, Any], *, previous_refresh: str | None = None
    ) -> TokenSet:
        access = body.get("access_token")
        if not isinstance(access, str) or not access:
            raise ProviderUnavailable(
                "token response without access_token", provider=self.name
            )
        refresh = body.get("refresh_token")
        return TokenSet(
            access_token=access,
            refresh_token=refresh
            if isinstance(refresh, str) and refresh
            else previous_refresh,
            expires_at=seconds_to_expiry(body.get("expires_in"), now=self._clock()),
            scopes=split_scopes(body.get("scope")),
        )

    async def exchange_code(
        self, *, code: str, redirect_uri: str, code_verifier: str | None = None
    ) -> TokenSet:
        client_id, secret = self._require_credentials()
        response = await self._http.request(
            "POST",
            TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "client_id": client_id,
                "client_secret": secret,
                "redirect_uri": redirect_uri,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            retries=0,
        )
        return self._tokens(json_object(response, self.name))

    async def refresh(self, tokens: TokenSet) -> TokenSet:
        if not tokens.refresh_token:
            raise ProviderAuthError(
                "LinkedIn issues no refresh token to this app, the user must reconnect",
                provider=self.name,
            )
        client_id, secret = self._require_credentials()
        response = await self._http.request(
            "POST",
            TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": tokens.refresh_token,
                "client_id": client_id,
                "client_secret": secret,
            },
            retries=0,
        )
        return self._tokens(
            json_object(response, self.name), previous_refresh=tokens.refresh_token
        )

    async def revoke(self, tokens: TokenSet) -> RevokeOutcome:
        client_id, secret = self._require_credentials()
        await self._http.request(
            "POST",
            REVOKE_URL,
            data={
                "token": tokens.access_token,
                "client_id": client_id,
                "client_secret": secret,
            },
            retries=0,
        )
        return RevokeOutcome(remote_revoked=True)

    async def get_account(self, tokens: TokenSet) -> AccountInfo:
        response = await self._http.request(
            "GET", f"{API_BASE}/v2/userinfo", headers=bearer(tokens), retries=1
        )
        body = json_object(response, self.name)
        sub = body.get("sub")
        if not sub:
            raise ProviderUnavailable("userinfo without sub", provider=self.name)
        can_read = READ_SCOPE in tokens.scopes
        return AccountInfo(
            external_id=str(sub),
            display_name=str(body.get("name") or sub),
            status="active" if can_read else "limited",
            note=None
            if can_read
            else "Publishing works. Reading posts and metrics needs r_member_social, which LinkedIn restricts.",
        )

    async def fetch_posts(
        self, tokens: TokenSet, account: AccountInfo, *, limit: int = 20
    ) -> list[PostIn]:
        if READ_SCOPE not in tokens.scopes:
            raise UnsupportedPlatform(
                "LinkedIn posts need the restricted r_member_social scope",
                provider=self.name,
            )
        response = await self._http.request(
            "GET",
            f"{API_BASE}/rest/posts",
            params={
                "author": f"urn:li:person:{account.external_id}",
                "q": "author",
                "count": max(1, min(limit, 100)),
            },
            headers=self._api_headers(tokens),
            retries=1,
        )
        rows = json_object(response, self.name).get("elements")
        posts: list[PostIn] = []
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict) or not row.get("id"):
                continue
            millis = row.get("publishedAt") or row.get("createdAt")
            if not isinstance(millis, int | float):
                continue
            posts.append(
                PostIn(
                    platform="linkedin",
                    external_id=str(row["id"]),
                    text=str(row.get("commentary") or ""),
                    published_at=datetime.fromtimestamp(millis / 1000, tz=UTC),
                    kind="original",
                    source="linkedin",
                )
            )
        return posts

    async def publish(
        self,
        tokens: TokenSet,
        account: AccountInfo,
        draft: PublishDraft,
        *,
        dry_run: bool = False,
    ) -> PublishResult:
        text = draft.text if not draft.link else f"{draft.text}\n{draft.link}"
        self.validate_draft(PublishDraft(text=text))
        if "w_member_social" not in tokens.scopes:
            raise ProviderAuthError(
                "the connection lacks the w_member_social scope", provider=self.name
            )
        if dry_run:
            return PublishResult(external_post_id=None, url=None, dry_run=True)
        response = await self._http.request(
            "POST",
            f"{API_BASE}/rest/posts",
            json={
                "author": f"urn:li:person:{account.external_id}",
                "commentary": escape_commentary(text),
                "visibility": "PUBLIC",
                "distribution": {
                    "feedDistribution": "MAIN_FEED",
                    "targetEntities": [],
                    "thirdPartyDistributionChannels": [],
                },
                "lifecycleState": "PUBLISHED",
                "isReshareDisabledByAuthor": False,
            },
            headers=self._api_headers(tokens),
            retries=0,
        )
        post_urn = response.headers.get("x-restli-id")
        if not post_urn:
            raise ProviderUnavailable(
                "post created without x-restli-id", provider=self.name
            )
        return PublishResult(
            external_post_id=post_urn,
            url=f"https://www.linkedin.com/feed/update/{post_urn}/",
            dry_run=False,
        )
