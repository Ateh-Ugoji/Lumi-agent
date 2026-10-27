"""X (Twitter) adapter, behind ``X_LIVE_ENABLED``.

Every call that would reach X's servers first calls ``_require_live``. With the switch off
the provider sends nothing, not even the code exchange, and raises ``LiveDisabled``. Building
the authorize URL is local arithmetic and stays allowed. A dry run is local too: it validates
the draft and reports the estimated cost, with no request.

Reads are not done here. X charges per resource read, so Lumi reads X through Xpoz.

Sources, checked 2026-10-27:
https://docs.x.com/fundamentals/authentication/oauth-2-0/authorization-code
https://docs.x.com/x-api/getting-started/pricing
"""

from __future__ import annotations

import re
from urllib.parse import urlencode

from ..config import ConnectionsConfig
from ..errors import (
    LiveDisabled,
    ProviderAuthError,
    ProviderUnavailable,
    ValidationFailed,
)
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

AUTHORIZE_URL = "https://x.com/i/oauth2/authorize"
API_BASE = "https://api.x.com"
TOKEN_URL = f"{API_BASE}/2/oauth2/token"
REVOKE_URL = f"{API_BASE}/2/oauth2/revoke"  # unverified in the docs of 2026-10-27
HOSTS = frozenset({"api.x.com"})
SCOPES = ("tweet.read", "tweet.write", "users.read", "offline.access", "media.write")
MAX_TEXT = 280
COST_POST_USD = 0.015
COST_POST_WITH_URL_USD = 0.20
COST_USER_READ_USD = 0.010
_URL = re.compile(r"https?://\S+", re.IGNORECASE)


def estimate_post_cost(text: str, link: str | None = None) -> float:
    """A post with a URL costs $0.20 and one without $0.015 (pricing page, 2026-10-27)."""
    return COST_POST_WITH_URL_USD if (link or _URL.search(text)) else COST_POST_USD


class XProvider(SocialProvider):
    name = "x"
    platform = "x"

    def __init__(self, http: ProviderHttp, config: ConnectionsConfig, **kwargs) -> None:
        super().__init__(http, **kwargs)
        self._config = config

    def _require_live(self) -> None:
        if not self._config.x_live_enabled:
            raise LiveDisabled(
                "X is switched off (X_LIVE_ENABLED=false). No request was sent.",
                provider=self.name,
            )

    def _require_credentials(self) -> tuple[str, str]:
        if not (self._config.x_client_id and self._config.x_client_secret):
            raise ProviderUnavailable(
                "X_CLIENT_ID and X_CLIENT_SECRET are not set", provider=self.name
            )
        return self._config.x_client_id, self._config.x_client_secret

    def capabilities(self) -> Capabilities:
        return Capabilities(
            can_publish=True,
            can_read_posts=False,
            can_read_metrics=False,
            uses_pkce=True,
            supports_refresh=True,
            max_text_length=MAX_TEXT,
            scopes=SCOPES,
            paid=True,
        )

    def build_authorize_url(
        self, *, state: str, redirect_uri: str, code_challenge: str | None = None
    ) -> AuthorizationRequest:
        if not code_challenge:
            raise ValueError("X requires a PKCE code_challenge")
        if not self._config.x_client_id:
            raise ProviderUnavailable("X_CLIENT_ID is not set", provider=self.name)
        query = urlencode(
            {
                "response_type": "code",
                "client_id": self._config.x_client_id,
                "redirect_uri": redirect_uri,
                "scope": " ".join(SCOPES),
                "state": state,
                "code_challenge": code_challenge,
                "code_challenge_method": "S256",
            }
        )
        return AuthorizationRequest(url=f"{AUTHORIZE_URL}?{query}", state=state)

    def _tokens(self, body: dict, *, previous_refresh: str | None = None) -> TokenSet:
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
            token_type=str(body.get("token_type") or "bearer"),
        )

    async def exchange_code(
        self, *, code: str, redirect_uri: str, code_verifier: str | None = None
    ) -> TokenSet:
        # The authorization code lives 30 seconds, so the exchange must follow the callback at once.
        self._require_live()
        if not code_verifier:
            raise ValueError("X requires the PKCE code_verifier")
        client_id, secret = self._require_credentials()
        response = await self._http.request(
            "POST",
            TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "code_verifier": code_verifier,
            },
            auth=(client_id, secret),
            retries=0,
        )
        return self._tokens(json_object(response, self.name))

    async def refresh(self, tokens: TokenSet) -> TokenSet:
        self._require_live()
        if not tokens.refresh_token:
            raise ProviderAuthError(
                "no refresh token, the user must reconnect", provider=self.name
            )
        client_id, secret = self._require_credentials()
        response = await self._http.request(
            "POST",
            TOKEN_URL,
            data={"grant_type": "refresh_token", "refresh_token": tokens.refresh_token},
            auth=(client_id, secret),
            retries=0,
        )
        return self._tokens(
            json_object(response, self.name), previous_refresh=tokens.refresh_token
        )

    async def revoke(self, tokens: TokenSet) -> RevokeOutcome:
        """Local disconnect always works. The remote call happens only when X is live."""
        if not self._config.x_live_enabled:
            return RevokeOutcome(remote_revoked=False, reason="x_live_disabled")
        client_id, secret = self._require_credentials()
        await self._http.request(
            "POST",
            REVOKE_URL,
            data={"token": tokens.access_token, "token_type_hint": "access_token"},
            auth=(client_id, secret),
            retries=0,
        )
        return RevokeOutcome(remote_revoked=True)

    async def get_account(self, tokens: TokenSet) -> AccountInfo:
        self._require_live()
        response = await self._http.request(
            "GET",
            f"{API_BASE}/2/users/me",
            params={"user.fields": "username,name"},
            headers=bearer(tokens),
            retries=1,
        )
        data = json_object(response, self.name).get("data")
        if not isinstance(data, dict) or not data.get("id"):
            raise ProviderUnavailable(
                "unexpected users/me response", provider=self.name
            )
        username = data.get("username")
        return AccountInfo(
            external_id=str(data["id"]),
            display_name=str(data.get("name") or username or data["id"]),
            handle=str(username).lower() if username else None,
            status="active",
        )

    async def publish(
        self,
        tokens: TokenSet,
        account: AccountInfo,
        draft: PublishDraft,
        *,
        dry_run: bool = False,
    ) -> PublishResult:
        self.validate_draft(draft)
        text = draft.text if not draft.link else f"{draft.text}\n{draft.link}"
        cost = estimate_post_cost(draft.text, draft.link)
        warnings = (
            ("The post has a link: X charges $0.20 instead of $0.015.",)
            if cost == COST_POST_WITH_URL_USD
            else ()
        )
        if len(text) > MAX_TEXT:
            raise ValidationFailed(
                f"the post has {len(text)} characters, X allows {MAX_TEXT}",
                provider=self.name,
            )
        if "tweet.write" not in tokens.scopes:
            raise ProviderAuthError(
                "the connection lacks the tweet.write scope", provider=self.name
            )
        if dry_run:
            return PublishResult(
                external_post_id=None,
                url=None,
                dry_run=True,
                estimated_cost_usd=cost,
                warnings=warnings,
            )
        self._require_live()
        response = await self._http.request(
            "POST",
            f"{API_BASE}/2/tweets",
            json={"text": text},
            headers=bearer(tokens),
            retries=0,
        )
        data = json_object(response, self.name).get("data")
        if not isinstance(data, dict) or not data.get("id"):
            raise ProviderUnavailable("unexpected tweets response", provider=self.name)
        post_id = str(data["id"])
        handle = account.handle
        url = (
            f"https://x.com/{handle}/status/{post_id}"
            if handle
            else f"https://x.com/i/status/{post_id}"
        )
        return PublishResult(
            external_post_id=post_id,
            url=url,
            dry_run=False,
            estimated_cost_usd=cost,
            warnings=warnings,
        )
