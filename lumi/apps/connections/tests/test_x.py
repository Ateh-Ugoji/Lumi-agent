from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from apps.connections.config import ConnectionsConfig
from apps.connections.errors import (
    BudgetExceeded,
    LiveDisabled,
    ProviderAuthError,
    ProviderUnavailable,
    RateLimited,
    UnsupportedOperation,
    ValidationFailed,
)
from apps.connections.providers.base import AccountInfo, PublishDraft, TokenSet
from apps.connections.providers.registry import build_provider

from .fakes import Recorder, json_response, routes

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)
ENV = {"X_CLIENT_ID": "x-id", "X_CLIENT_SECRET": "x-sec"}
TOKENS = TokenSet(
    access_token="x-access-FAKE",
    refresh_token="x-refresh-FAKE",
    scopes=("tweet.read", "tweet.write", "users.read", "offline.access"),
)
ACCOUNT = AccountInfo(
    external_id="2244994945", display_name="Lumi Test", handle="lumitest"
)
VERIFIER = "v" * 64


def make(live: bool, handler=None):
    config = ConnectionsConfig.from_env(
        {**ENV, "X_LIVE_ENABLED": "true" if live else "false"}
    )
    rec = Recorder(handler or (lambda r: httpx.Response(500)))
    return build_provider("x", config, transport=rec.transport, clock=lambda: NOW), rec


# --- The switch is off: zero requests -------------------------------------------------------


async def test_every_network_operation_raises_live_disabled_and_sends_nothing() -> None:
    def forbidden(request: httpx.Request) -> httpx.Response:
        pytest.fail(
            f"X must not be called while X_LIVE_ENABLED=false: {request.url.host}"
        )

    provider, rec = make(live=False, handler=forbidden)
    draft = PublishDraft(text="hola")
    calls = [
        provider.exchange_code(
            code="c", redirect_uri="http://127.0.0.1/cb", code_verifier=VERIFIER
        ),
        provider.refresh(TOKENS),
        provider.get_account(TOKENS),
        provider.list_accounts(TOKENS),
        provider.publish(TOKENS, ACCOUNT, draft),
    ]
    for call in calls:
        with pytest.raises(LiveDisabled):
            await call
    assert rec.requests == []
    assert not [h for h in rec.hosts if h.endswith("x.com")]


async def test_reads_are_unsupported_not_silently_empty() -> None:
    provider, rec = make(live=False)
    with pytest.raises(UnsupportedOperation):
        await provider.fetch_posts(TOKENS, ACCOUNT)
    with pytest.raises(UnsupportedOperation):
        await provider.fetch_metrics(TOKENS, ACCOUNT, "1")
    assert rec.requests == []


async def test_local_disconnect_works_with_x_off_and_calls_nothing() -> None:
    provider, rec = make(live=False)
    outcome = await provider.revoke(TOKENS)
    assert outcome.remote_revoked is False and outcome.reason == "x_live_disabled"
    assert rec.requests == []


async def test_authorize_url_and_dry_run_are_local_with_x_off() -> None:
    provider, rec = make(live=False)
    request = provider.build_authorize_url(
        state="st",
        redirect_uri="http://127.0.0.1:8000/api/v1/connections/x/callback",
        code_challenge="ch",
    )
    query = parse_qs(urlsplit(request.url).query)
    assert request.url.startswith("https://x.com/i/oauth2/authorize?")
    assert query["scope"] == [
        "tweet.read tweet.write users.read offline.access media.write"
    ]
    assert query["code_challenge_method"] == ["S256"]
    result = await provider.publish(
        TOKENS, ACCOUNT, PublishDraft(text="hola"), dry_run=True
    )
    assert result.dry_run and result.estimated_cost_usd == 0.015
    assert rec.requests == []


async def test_dry_run_warns_about_the_link_surcharge() -> None:
    provider, _ = make(live=False)
    result = await provider.publish(
        TOKENS,
        ACCOUNT,
        PublishDraft(text="mira esto https://example.com/a"),
        dry_run=True,
    )
    assert result.estimated_cost_usd == 0.20
    assert result.warnings
    separate = await provider.publish(
        TOKENS,
        ACCOUNT,
        PublishDraft(text="mira esto", link="https://example.com"),
        dry_run=True,
    )
    assert separate.estimated_cost_usd == 0.20


def test_authorize_url_requires_pkce() -> None:
    provider, _ = make(live=False)
    with pytest.raises(ValueError):
        provider.build_authorize_url(state="s", redirect_uri="http://127.0.0.1/cb")


# --- The switch is on: mocked responses only -----------------------------------------------


async def test_exchange_code_uses_basic_auth_pkce_and_parses_tokens() -> None:
    seen: dict = {}

    def token(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers["authorization"]
        seen["body"] = dict(httpx.QueryParams(request.content.decode()))
        return json_response("x_token.json")

    provider, rec = make(
        live=True, handler=routes({("POST", "/2/oauth2/token"): token})
    )
    tokens = await provider.exchange_code(
        code="c0de", redirect_uri="http://127.0.0.1/cb", code_verifier=VERIFIER
    )
    assert seen["auth"].startswith("Basic ")
    assert seen["body"] == {
        "grant_type": "authorization_code",
        "code": "c0de",
        "redirect_uri": "http://127.0.0.1/cb",
        "code_verifier": VERIFIER,
    }
    assert (
        tokens.access_token == "x-access-FAKE"
        and tokens.refresh_token == "x-refresh-FAKE"
    )
    assert (
        tokens.expires_at is not None
        and (tokens.expires_at - NOW).total_seconds() == 7200
    )
    assert "tweet.write" in tokens.scopes
    assert set(rec.hosts) == {"api.x.com"}


async def test_refresh_keeps_the_old_refresh_token_when_x_sends_none() -> None:
    body = {
        "token_type": "bearer",
        "expires_in": 7200,
        "access_token": "new",
        "scope": "tweet.write",
    }
    provider, _ = make(
        live=True,
        handler=routes({("POST", "/2/oauth2/token"): httpx.Response(200, json=body)}),
    )
    fresh = await provider.refresh(TOKENS)
    assert fresh.access_token == "new" and fresh.refresh_token == "x-refresh-FAKE"


async def test_refresh_without_refresh_token_needs_reconnect() -> None:
    provider, rec = make(live=True)
    with pytest.raises(ProviderAuthError):
        await provider.refresh(TokenSet(access_token="a"))
    assert rec.requests == []


async def test_revoked_refresh_token_is_an_auth_error() -> None:
    provider, _ = make(
        live=True,
        handler=routes(
            {
                ("POST", "/2/oauth2/token"): httpx.Response(
                    400, json={"error": "invalid_grant"}
                )
            }
        ),
    )
    with pytest.raises(ProviderAuthError):
        await provider.refresh(TOKENS)


async def test_get_account_and_publish_build_the_post_url() -> None:
    sent: dict = {}

    def tweet(request: httpx.Request) -> httpx.Response:
        sent["json"] = request.read().decode()
        sent["auth"] = request.headers["authorization"]
        return json_response("x_tweet.json", 201)

    provider, _ = make(
        live=True,
        handler=routes(
            {
                ("GET", "/2/users/me"): json_response("x_me.json"),
                ("POST", "/2/tweets"): tweet,
            }
        ),
    )
    account = await provider.get_account(TOKENS)
    assert (account.external_id, account.handle) == ("2244994945", "lumitest")
    result = await provider.publish(TOKENS, account, PublishDraft(text="hola"))
    assert result.external_post_id == "1445880548472328192"
    assert result.url == "https://x.com/lumitest/status/1445880548472328192"
    assert sent["json"] == '{"text":"hola"}' and sent["auth"] == "Bearer x-access-FAKE"


async def test_publish_is_never_retried() -> None:
    provider, rec = make(
        live=True, handler=routes({("POST", "/2/tweets"): httpx.Response(503)})
    )
    with pytest.raises(ProviderUnavailable):
        await provider.publish(TOKENS, ACCOUNT, PublishDraft(text="hola"))
    assert len(rec.requests) == 1


@pytest.mark.parametrize(
    ("status", "error"),
    [(401, ProviderAuthError), (402, BudgetExceeded), (429, RateLimited)],
)
async def test_publish_errors_are_typed(status: int, error: type[Exception]) -> None:
    provider, _ = make(
        live=True, handler=routes({("POST", "/2/tweets"): httpx.Response(status)})
    )
    with pytest.raises(error):
        await provider.publish(TOKENS, ACCOUNT, PublishDraft(text="hola"))


async def test_publish_validation_happens_before_any_request() -> None:
    provider, rec = make(live=True)
    with pytest.raises(ValidationFailed):
        await provider.publish(TOKENS, ACCOUNT, PublishDraft(text="  "))
    with pytest.raises(ValidationFailed):
        await provider.publish(TOKENS, ACCOUNT, PublishDraft(text="a" * 281))
    with pytest.raises(ValidationFailed):
        await provider.publish(
            TOKENS,
            ACCOUNT,
            PublishDraft(text="a" * 270, link="https://example.com/long"),
        )
    with pytest.raises(ProviderAuthError):
        await provider.publish(
            TokenSet(access_token="a", scopes=("tweet.read",)),
            ACCOUNT,
            PublishDraft(text="hi"),
        )
    assert rec.requests == []


async def test_missing_client_credentials_are_reported_without_a_request() -> None:
    config = ConnectionsConfig.from_env({"X_LIVE_ENABLED": "true"})
    rec = Recorder(lambda r: httpx.Response(500))
    provider = build_provider("x", config, transport=rec.transport)
    with pytest.raises(ProviderUnavailable):
        await provider.exchange_code(
            code="c", redirect_uri="http://127.0.0.1/cb", code_verifier=VERIFIER
        )
    assert rec.requests == []
