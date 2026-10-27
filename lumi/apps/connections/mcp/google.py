"""Google OAuth for the MCP connectors.

It is not a social network, so it is not a ``SocialProvider``, but it has the four members
``OAuthFlow`` calls (``name``, ``capabilities``, ``build_authorize_url``, ``exchange_code``) and
adds ``refresh`` and ``revoke``. Tokens stay in ``TokenSet`` and out of every message.

Sources: https://developers.google.com/identity/protocols/oauth2/web-server
The refresh token only comes back on the first consent or a forced one (``prompt=consent``), so
a refresh response without one keeps the stored value.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

import httpx

from ..config import ConnectionsConfig
from ..errors import ProviderAuthError, ProviderUnavailable
from ..http import ProviderHttp
from ..providers.base import (
    AuthorizationRequest,
    Capabilities,
    RevokeOutcome,
    TokenSet,
    json_object,
    seconds_to_expiry,
    split_scopes,
    utcnow,
)
from .connectors import (
    GOOGLE_REVOKE_URL,
    GOOGLE_TOKEN_URL,
    google_consent_url,
    google_scope_union,
)

HOSTS = frozenset({"accounts.google.com", "oauth2.googleapis.com"})


class GoogleOAuth:
    name = "google"

    def __init__(
        self,
        config: ConnectionsConfig,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._config = config
        self._http = ProviderHttp("google", allowed_hosts=HOSTS, transport=transport)
        self._clock = clock

    def capabilities(self) -> Capabilities:
        return Capabilities(
            can_publish=False,
            can_read_posts=False,
            can_read_metrics=False,
            uses_pkce=True,
            supports_refresh=True,
            max_text_length=0,
            scopes=tuple(google_scope_union()),
        )

    def _credentials(self) -> tuple[str, str]:
        if not (self._config.google_client_id and self._config.google_client_secret):
            raise ProviderAuthError(
                "Google OAuth client is not set", provider=self.name
            )
        return self._config.google_client_id, self._config.google_client_secret

    def build_authorize_url(
        self, *, state: str, redirect_uri: str, code_challenge: str | None = None
    ) -> AuthorizationRequest:
        client_id, _ = self._credentials()
        url = google_consent_url(
            state=state,
            redirect_uri=redirect_uri,
            client_id=client_id,
            code_challenge=code_challenge,
        )
        return AuthorizationRequest(url=url, state=state)

    async def exchange_code(
        self, *, code: str, redirect_uri: str, code_verifier: str | None = None
    ) -> TokenSet:
        client_id, secret = self._credentials()
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": client_id,
            "client_secret": secret,
        }
        if code_verifier:
            data["code_verifier"] = code_verifier
        response = await self._http.request("POST", GOOGLE_TOKEN_URL, data=data)
        return self._tokens(json_object(response, self.name), previous=None)

    async def refresh(self, tokens: TokenSet) -> TokenSet:
        if not tokens.refresh_token:
            raise ProviderAuthError(
                "no refresh token is stored, the user must reconnect Google",
                provider=self.name,
            )
        client_id, secret = self._credentials()
        response = await self._http.request(
            "POST",
            GOOGLE_TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": tokens.refresh_token,
                "client_id": client_id,
                "client_secret": secret,
            },
            retries=1,
        )
        return self._tokens(json_object(response, self.name), previous=tokens)

    async def revoke(self, tokens: TokenSet) -> RevokeOutcome:
        token = tokens.refresh_token or tokens.access_token
        await self._http.request("POST", GOOGLE_REVOKE_URL, data={"token": token})
        return RevokeOutcome(remote_revoked=True)

    def _tokens(self, body: dict, *, previous: TokenSet | None) -> TokenSet:
        access = body.get("access_token")
        if not isinstance(access, str) or not access:
            raise ProviderUnavailable(
                "token response without access_token", provider=self.name
            )
        refresh = body.get("refresh_token")
        if not isinstance(refresh, str) or not refresh:
            refresh = previous.refresh_token if previous else None
        scopes = split_scopes(body.get("scope")) or (
            previous.scopes if previous else ()
        )
        return TokenSet(
            access_token=access,
            refresh_token=refresh,
            expires_at=seconds_to_expiry(body.get("expires_in"), now=self._clock()),
            scopes=scopes,
            token_type=str(body.get("token_type") or "Bearer"),
        )
