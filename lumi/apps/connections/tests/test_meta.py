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
    ValidationFailed,
)
from apps.connections.providers.base import AccountInfo, PublishDraft, TokenSet
from apps.connections.providers.registry import build_provider

from .fakes import Recorder, json_response, routes

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)
CONFIG = ConnectionsConfig.from_env(
    {"META_APP_ID": "app-1", "META_APP_SECRET": "sec-1"}
)
USER = TokenSet(access_token="meta-long-FAKE")
PAGE = AccountInfo(
    external_id="1001", display_name="Pagina Uno", access_token="meta-page1-FAKE"
)


def _form(request: httpx.Request) -> dict[str, str]:
    return dict(httpx.QueryParams(request.content.decode()))


def make(handler=None):
    rec = Recorder(handler or (lambda r: httpx.Response(500)))
    return build_provider(
        "meta", CONFIG, transport=rec.transport, clock=lambda: NOW
    ), rec


def test_authorize_url_has_scopes_state_and_version() -> None:
    provider, rec = make()
    request = provider.build_authorize_url(
        state="st",
        redirect_uri="http://localhost:3010/connections/meta/callback",
    )
    parts = urlsplit(request.url)
    query = parse_qs(parts.query)
    assert parts.netloc == "www.facebook.com" and parts.path == "/v26.0/dialog/oauth"
    assert query["state"] == ["st"] and query["client_id"] == ["app-1"]
    assert query["scope"] == [
        "pages_show_list,pages_read_engagement,pages_manage_posts,read_insights"
    ]
    assert "client_secret" not in request.url
    assert rec.requests == []


async def test_exchange_code_swaps_for_a_long_lived_token() -> None:
    steps: list[dict] = []

    def token(request: httpx.Request) -> httpx.Response:
        params = _form(request)
        steps.append(params)
        return json_response(
            "meta_long_token.json"
            if params.get("grant_type")
            else "meta_short_token.json"
        )

    provider, _ = make(routes({("POST", "/v26.0/oauth/access_token"): token}))
    tokens = await provider.exchange_code(
        code="c0de", redirect_uri="http://localhost:8000/cb"
    )
    assert tokens.access_token == "meta-long-FAKE"
    assert steps[0]["code"] == "c0de" and steps[0]["client_secret"] == "sec-1"
    assert (
        steps[1]["grant_type"] == "fb_exchange_token"
        and steps[1]["fb_exchange_token"] == "meta-short-FAKE"
    )
    assert tokens.expires_at is not None


async def test_missing_app_credentials_fail_before_any_request() -> None:
    rec = Recorder(lambda r: httpx.Response(500))
    provider = build_provider(
        "meta", ConnectionsConfig.from_env({}), transport=rec.transport
    )
    with pytest.raises(ProviderUnavailable):
        await provider.exchange_code(code="c", redirect_uri="http://localhost/cb")
    with pytest.raises(ProviderUnavailable):
        provider.build_authorize_url(state="s", redirect_uri="http://localhost/cb")
    assert rec.requests == []


async def test_list_accounts_keeps_page_tokens_and_marks_limited_pages() -> None:
    provider, _ = make(
        routes({("GET", "/v26.0/me/accounts"): json_response("meta_accounts.json")})
    )
    pages = await provider.list_accounts(USER)
    assert [p.external_id for p in pages] == [
        "1001",
        "1002",
    ]  # the page without a token is dropped
    assert pages[0].status == "active" and pages[0].access_token == "meta-page1-FAKE"
    assert pages[1].status == "limited" and pages[1].note
    assert "meta-page1-FAKE" not in repr(pages[0])


async def test_get_account_reads_me() -> None:
    provider, _ = make(routes({("GET", "/v26.0/me"): json_response("meta_me.json")}))
    account = await provider.get_account(USER)
    assert (account.external_id, account.display_name) == ("9001", "Christian")


async def test_publish_posts_to_the_page_feed_with_the_page_token() -> None:
    sent: dict = {}

    def feed(request: httpx.Request) -> httpx.Response:
        sent["body"] = dict(httpx.QueryParams(request.content.decode()))
        sent["query"] = dict(request.url.params)
        return json_response("meta_feed.json")

    provider, _ = make(routes({("POST", "/v26.0/1001/feed"): feed}))
    result = await provider.publish(
        USER, PAGE, PublishDraft(text="Hola", link="https://example.com")
    )
    assert result.external_post_id == "1001_555"
    assert result.url == "https://www.facebook.com/1001_555"
    assert sent["body"] == {
        "message": "Hola",
        "access_token": "meta-page1-FAKE",
        "link": "https://example.com",
    }
    assert sent["query"] == {}  # secrets travel in the body, not in the URL


async def test_publish_dry_run_and_validation_send_nothing() -> None:
    provider, rec = make()
    assert (
        await provider.publish(USER, PAGE, PublishDraft(text="hi"), dry_run=True)
    ).dry_run
    with pytest.raises(ValidationFailed):
        await provider.publish(USER, PAGE, PublishDraft(text=""))
    limited = AccountInfo(
        external_id="1002", display_name="x", status="limited", note="no task"
    )
    with pytest.raises(ProviderAuthError):
        await provider.publish(USER, limited, PublishDraft(text="hi"))
    assert rec.requests == []


async def test_fetch_posts_parses_and_skips_rows_without_id_or_time() -> None:
    provider, _ = make(
        routes({("GET", "/v26.0/1001/posts"): json_response("meta_posts.json")})
    )
    posts = await provider.fetch_posts(USER, PAGE, limit=500)
    assert [p.external_id for p in posts] == ["1001_555", "1001_556"]
    assert (
        posts[0].platform == "facebook"
        and posts[0].source == "meta"
        and posts[0].kind == "original"
    )
    assert posts[0].published_at == datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
    assert posts[1].text == ""


async def test_fetch_posts_caps_limit_at_100() -> None:
    seen: dict = {}

    def posts(request: httpx.Request) -> httpx.Response:
        seen.update(request.url.params)
        return httpx.Response(200, json={"data": []})

    provider, _ = make(routes({("GET", "/v26.0/1001/posts"): posts}))
    await provider.fetch_posts(USER, PAGE, limit=500)
    assert seen["limit"] == "100"


async def test_fetch_metrics_uses_the_v25_metric_names() -> None:
    seen: dict = {}

    def insights(request: httpx.Request) -> httpx.Response:
        seen.update(request.url.params)
        return json_response("meta_insights.json")

    provider, _ = make(routes({("GET", "/v26.0/1001_555/insights"): insights}))
    metrics = await provider.fetch_metrics(USER, PAGE, "1001_555")
    assert metrics.views == 321 and metrics.likes is None
    assert seen["metric"] == "post_media_view,post_total_media_view_unique"
    assert "impressions" not in seen["metric"]


async def test_expired_token_190_is_an_auth_error_even_on_http_400() -> None:
    provider, _ = make(
        routes({("GET", "/v26.0/me"): json_response("meta_error_190.json", 400)})
    )
    with pytest.raises(ProviderAuthError) as info:
        await provider.get_account(USER)
    assert "meta-long-FAKE" not in str(info.value)


async def test_app_level_throttle_code_4_is_rate_limited() -> None:
    provider, _ = make(
        routes({("GET", "/v26.0/1001/posts"): json_response("meta_error_4.json", 400)})
    )
    with pytest.raises(RateLimited):
        await provider.fetch_posts(USER, PAGE)


async def test_revoke_calls_delete_permissions() -> None:
    provider, rec = make(
        routes(
            {
                ("DELETE", "/v26.0/me/permissions"): httpx.Response(
                    200, json={"success": True}
                )
            }
        )
    )
    assert (await provider.revoke(USER)).remote_revoked is True
    assert rec.requests[0].method == "DELETE"


async def test_refresh_repeats_the_long_lived_exchange() -> None:
    seen: dict = {}

    def token(request: httpx.Request) -> httpx.Response:
        seen.update(_form(request))
        return json_response("meta_long_token.json")

    provider, _ = make(routes({("POST", "/v26.0/oauth/access_token"): token}))
    fresh = await provider.refresh(USER)
    assert (
        fresh.access_token == "meta-long-FAKE"
        and seen["fb_exchange_token"] == "meta-long-FAKE"
    )


async def test_only_graph_host_is_ever_contacted() -> None:
    provider, rec = make(
        routes(
            {
                ("GET", "/v26.0/me/accounts"): json_response("meta_accounts.json"),
                ("GET", "/v26.0/me"): json_response("meta_me.json"),
            }
        )
    )
    await provider.list_accounts(USER)
    await provider.get_account(USER)
    assert set(rec.hosts) == {"graph.facebook.com"}


async def test_no_secret_ever_appears_in_a_request_url() -> None:
    """httpx logs every URL at INFO, so a token or the app secret in a query leaks to the logs."""
    provider, rec = make(
        routes(
            {
                ("POST", "/v26.0/oauth/access_token"): json_response(
                    "meta_long_token.json"
                ),
                ("GET", "/v26.0/me"): json_response("meta_me.json"),
                ("GET", "/v26.0/me/accounts"): json_response("meta_accounts.json"),
                ("GET", "/v26.0/1001/posts"): httpx.Response(200, json={"data": []}),
                ("GET", "/v26.0/1001_555/insights"): json_response(
                    "meta_insights.json"
                ),
                ("DELETE", "/v26.0/me/permissions"): httpx.Response(
                    200, json={"success": True}
                ),
            }
        )
    )
    await provider.exchange_code(code="c0de", redirect_uri="http://localhost:8000/cb")
    await provider.check_app_credentials()
    await provider.refresh(USER)
    await provider.get_account(USER)
    await provider.list_accounts(USER)
    await provider.fetch_posts(USER, PAGE)
    await provider.fetch_metrics(USER, PAGE, "1001_555")
    await provider.revoke(USER)
    assert len(rec.requests) >= 8
    for request in rec.requests:
        url = str(request.url)
        assert "FAKE" not in url and "sec-1" not in url and "c0de" not in url, url
    me = next(r for r in rec.requests if r.url.path.endswith("/me"))
    assert me.headers["authorization"] == "Bearer meta-long-FAKE"
