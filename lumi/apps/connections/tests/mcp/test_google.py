from __future__ import annotations

from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from apps.connections.config import ConnectionsConfig
from apps.connections.errors import ProviderAuthError, ProviderUnavailable
from apps.connections.http import HostNotAllowed
from apps.connections.mcp.google import GoogleOAuth
from apps.connections.providers.base import TokenSet

from ..fakes import Recorder

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)
CONFIG = ConnectionsConfig.from_env(
    {"GOOGLE_OAUTH_CLIENT_ID": "g-id", "GOOGLE_OAUTH_CLIENT_SECRET": "g-sec"}
)


def make(handler, config=CONFIG):
    rec = Recorder(handler)
    return GoogleOAuth(config, transport=rec.transport, clock=lambda: NOW), rec


def form(request: httpx.Request) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(request.content.decode()).items()}


async def test_exchange_code_sends_the_verifier_and_returns_tokens():
    google, rec = make(
        lambda r: httpx.Response(
            200,
            json={
                "access_token": "ya29-FAKE",
                "refresh_token": "1//-FAKE",
                "expires_in": 3600,
                "scope": "a b",
                "token_type": "Bearer",
            },
        )
    )
    tokens = await google.exchange_code(
        code="c0de", redirect_uri="http://x/cb", code_verifier="ver"
    )
    sent = form(rec.requests[0])
    assert rec.requests[0].url.host == "oauth2.googleapis.com"
    assert sent["grant_type"] == "authorization_code"
    assert sent["code_verifier"] == "ver" and sent["client_secret"] == "g-sec"
    assert tokens.access_token == "ya29-FAKE" and tokens.refresh_token == "1//-FAKE"
    assert tokens.expires_at == NOW + timedelta(seconds=3600)
    assert tokens.scopes == ("a", "b")


async def test_refresh_keeps_the_old_refresh_token_and_scopes():
    google, rec = make(
        lambda r: httpx.Response(200, json={"access_token": "new", "expires_in": 3599})
    )
    old = TokenSet(access_token="old", refresh_token="RT", scopes=("s1",))
    fresh = await google.refresh(old)
    assert form(rec.requests[0])["refresh_token"] == "RT"
    assert fresh.access_token == "new"
    assert fresh.refresh_token == "RT" and fresh.scopes == ("s1",)


async def test_dead_grant_is_an_auth_error_not_an_outage():
    google, _ = make(lambda r: httpx.Response(400, json={"error": "invalid_grant"}))
    with pytest.raises(ProviderAuthError):
        await google.refresh(TokenSet(access_token="x", refresh_token="RT"))


async def test_refresh_without_a_stored_refresh_token_asks_to_reconnect():
    google, rec = make(lambda r: httpx.Response(500))
    with pytest.raises(ProviderAuthError):
        await google.refresh(TokenSet(access_token="x"))
    assert rec.requests == []


async def test_outage_is_unavailable_and_the_message_hides_secrets():
    google, _ = make(lambda r: httpx.Response(503, text="boom g-sec"))
    with pytest.raises(ProviderUnavailable) as caught:
        await google.exchange_code(code="c", redirect_uri="http://x/cb")
    assert "g-sec" not in str(caught.value)


async def test_token_response_without_access_token_is_unavailable():
    google, _ = make(lambda r: httpx.Response(200, json={"expires_in": 5}))
    with pytest.raises(ProviderUnavailable):
        await google.exchange_code(code="c", redirect_uri="http://x/cb")


async def test_revoke_prefers_the_refresh_token():
    google, rec = make(lambda r: httpx.Response(200, json={}))
    outcome = await google.revoke(TokenSet(access_token="AT", refresh_token="RT"))
    assert outcome.remote_revoked and form(rec.requests[0])["token"] == "RT"


def test_authorize_url_without_credentials_is_an_auth_error():
    empty = ConnectionsConfig.from_env({})
    with pytest.raises(ProviderAuthError):
        GoogleOAuth(empty).build_authorize_url(state="s", redirect_uri="http://x/cb")


def test_authorize_url_uses_the_client_and_pkce():
    google, _ = make(lambda r: httpx.Response(500))
    request = google.build_authorize_url(
        state="s", redirect_uri="http://x/cb", code_challenge="ch"
    )
    q = parse_qs(urlsplit(request.url).query)
    assert q["client_id"] == ["g-id"] and q["code_challenge"] == ["ch"]
    assert google.capabilities().uses_pkce


async def test_only_google_hosts_are_reachable():
    google, rec = make(lambda r: httpx.Response(200, json={}))
    with pytest.raises(HostNotAllowed):
        await google._http.request("GET", "https://evil.example.com/token")
    assert rec.requests == []
