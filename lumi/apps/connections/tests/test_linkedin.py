from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from apps.connections.config import ConnectionsConfig
from apps.connections.errors import (
    ProviderAuthError,
    ProviderUnavailable,
    RateLimited,
    UnsupportedOperation,
    UnsupportedPlatform,
    ValidationFailed,
)
from apps.connections.providers.base import AccountInfo, PublishDraft, TokenSet
from apps.connections.providers.linkedin import escape_commentary
from apps.connections.providers.registry import build_provider

from .fakes import Recorder, json_response, routes

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)
CONFIG = ConnectionsConfig.from_env(
    {"LINKEDIN_CLIENT_ID": "li-id", "LINKEDIN_CLIENT_SECRET": "li-sec"}
)
TOKENS = TokenSet(
    access_token="li-access-FAKE",
    scopes=("openid", "profile", "email", "w_member_social"),
)
ACCOUNT = AccountInfo(external_id="782bbtaQ", display_name="Christian")


def make(handler=None):
    rec = Recorder(handler or (lambda r: httpx.Response(500)))
    return build_provider(
        "linkedin", CONFIG, transport=rec.transport, clock=lambda: NOW
    ), rec


def test_authorize_url() -> None:
    provider, rec = make()
    request = provider.build_authorize_url(
        state="st", redirect_uri="https://t.example/cb"
    )
    parts = urlsplit(request.url)
    query = parse_qs(parts.query)
    assert (parts.netloc, parts.path) == ("www.linkedin.com", "/oauth/v2/authorization")
    assert query["scope"] == ["openid profile email w_member_social"]
    assert query["state"] == ["st"] and query["response_type"] == ["code"]
    assert "r_member_social" not in request.url
    assert rec.requests == []


async def test_exchange_code_parses_comma_separated_scopes_and_60_day_expiry() -> None:
    seen: dict = {}

    def token(request: httpx.Request) -> httpx.Response:
        seen.update(dict(httpx.QueryParams(request.content.decode())))
        return json_response("linkedin_token.json")

    provider, _ = make(routes({("POST", "/oauth/v2/accessToken"): token}))
    tokens = await provider.exchange_code(
        code="c0de", redirect_uri="https://t.example/cb"
    )
    assert seen["grant_type"] == "authorization_code" and seen["code"] == "c0de"
    assert tokens.scopes == ("openid", "profile", "email", "w_member_social")
    assert tokens.refresh_token is None
    assert (tokens.expires_at - NOW).days == 60


async def test_refresh_without_refresh_token_asks_to_reconnect() -> None:
    provider, rec = make()
    with pytest.raises(ProviderAuthError):
        await provider.refresh(TOKENS)
    assert rec.requests == []


async def test_refresh_with_a_partner_refresh_token() -> None:
    provider, _ = make(
        routes(
            {
                ("POST", "/oauth/v2/accessToken"): httpx.Response(
                    200, json={"access_token": "n", "expires_in": 60}
                )
            }
        )
    )
    fresh = await provider.refresh(TokenSet(access_token="o", refresh_token="r"))
    assert fresh.access_token == "n" and fresh.refresh_token == "r"


async def test_account_without_r_member_social_is_limited() -> None:
    provider, _ = make(
        routes({("GET", "/v2/userinfo"): json_response("linkedin_userinfo.json")})
    )
    account = await provider.get_account(TOKENS)
    assert (
        account.external_id == "782bbtaQ"
        and account.status == "limited"
        and account.note
    )
    assert "email" not in repr(account)


async def test_account_with_r_member_social_is_active() -> None:
    provider, _ = make(
        routes({("GET", "/v2/userinfo"): json_response("linkedin_userinfo.json")})
    )
    full = TokenSet(access_token="a", scopes=("w_member_social", "r_member_social"))
    assert (await provider.get_account(full)).status == "active"


async def test_publish_sends_the_version_headers_and_escapes_markup() -> None:
    seen: dict = {}

    def post(request: httpx.Request) -> httpx.Response:
        seen["headers"] = request.headers
        seen["json"] = __import__("json").loads(request.read())
        return httpx.Response(
            201, headers={"x-restli-id": "urn:li:share:6844785523593134080"}
        )

    provider, _ = make(routes({("POST", "/rest/posts"): post}))
    result = await provider.publish(
        TOKENS, ACCOUNT, PublishDraft(text="Hola (mundo) #lumi *x*")
    )
    assert seen["headers"]["linkedin-version"] == "202609"
    assert seen["headers"]["x-restli-protocol-version"] == "2.0.0"
    assert seen["headers"]["authorization"] == "Bearer li-access-FAKE"
    body = seen["json"]
    assert body["author"] == "urn:li:person:782bbtaQ"
    assert body["commentary"] == r"Hola \(mundo\) \#lumi \*x\*"
    assert body["lifecycleState"] == "PUBLISHED" and body["visibility"] == "PUBLIC"
    assert result.external_post_id == "urn:li:share:6844785523593134080"
    assert (
        result.url
        == "https://www.linkedin.com/feed/update/urn:li:share:6844785523593134080/"
    )


def test_escape_covers_every_reserved_character() -> None:
    reserved = r"\|{}@[]()<>#*_~"
    assert escape_commentary(reserved) == "".join("\\" + c for c in reserved)
    assert escape_commentary("plain text, 100%") == "plain text, 100%"


async def test_api_version_follows_configuration() -> None:
    config = ConnectionsConfig.from_env({"LINKEDIN_API_VERSION": "202610"})
    seen: dict = {}

    def post(request: httpx.Request) -> httpx.Response:
        seen["v"] = request.headers["linkedin-version"]
        return httpx.Response(201, headers={"x-restli-id": "urn:li:share:1"})

    rec = Recorder(routes({("POST", "/rest/posts"): post}))
    provider = build_provider("linkedin", config, transport=rec.transport)
    await provider.publish(TOKENS, ACCOUNT, PublishDraft(text="hi"))
    assert seen["v"] == "202610"


async def test_publish_guards_run_before_any_request() -> None:
    provider, rec = make()
    assert (
        await provider.publish(TOKENS, ACCOUNT, PublishDraft(text="hi"), dry_run=True)
    ).dry_run
    with pytest.raises(ValidationFailed):
        await provider.publish(TOKENS, ACCOUNT, PublishDraft(text="a" * 3001))
    with pytest.raises(ProviderAuthError):
        await provider.publish(
            TokenSet(access_token="a", scopes=("openid",)),
            ACCOUNT,
            PublishDraft(text="hi"),
        )
    assert rec.requests == []


async def test_publish_without_restli_id_is_flagged_not_swallowed() -> None:
    provider, _ = make(routes({("POST", "/rest/posts"): httpx.Response(201)}))
    with pytest.raises(ProviderUnavailable):
        await provider.publish(TOKENS, ACCOUNT, PublishDraft(text="hi"))


@pytest.mark.parametrize(
    ("status", "error"),
    [(401, ProviderAuthError), (403, ProviderAuthError), (429, RateLimited)],
)
async def test_publish_errors_are_typed(status: int, error: type[Exception]) -> None:
    provider, rec = make(routes({("POST", "/rest/posts"): httpx.Response(status)}))
    with pytest.raises(error):
        await provider.publish(TOKENS, ACCOUNT, PublishDraft(text="hi"))
    assert len(rec.requests) == 1


async def test_reading_posts_needs_the_restricted_scope() -> None:
    provider, rec = make()
    with pytest.raises(UnsupportedPlatform):
        await provider.fetch_posts(TOKENS, ACCOUNT)
    with pytest.raises(UnsupportedOperation):
        await provider.fetch_metrics(TOKENS, ACCOUNT, "x")
    assert rec.requests == []


async def test_fetch_posts_with_the_scope_parses_elements() -> None:
    provider, _ = make(
        routes({("GET", "/rest/posts"): json_response("linkedin_posts.json")})
    )
    full = TokenSet(access_token="a", scopes=("r_member_social",))
    posts = await provider.fetch_posts(full, ACCOUNT)
    assert [p.external_id for p in posts] == ["urn:li:share:1"]
    assert posts[0].platform == "linkedin" and posts[0].published_at.year == 2025


async def test_only_linkedin_hosts_are_contacted() -> None:
    provider, rec = make(
        routes(
            {
                ("GET", "/v2/userinfo"): json_response("linkedin_userinfo.json"),
                ("POST", "/oauth/v2/accessToken"): json_response("linkedin_token.json"),
            }
        )
    )
    await provider.get_account(TOKENS)
    await provider.exchange_code(code="c", redirect_uri="https://t.example/cb")
    assert set(rec.hosts) <= {"api.linkedin.com", "www.linkedin.com"}
