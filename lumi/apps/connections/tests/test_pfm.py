from __future__ import annotations

import json

import httpx
import pytest

from apps.connections.clients import pfm
from apps.connections.clients.limiter import SlidingWindowLimiter
from apps.connections.clients.pfm import PFM_PERMISSIONS, PfmClient
from apps.connections.config import ConnectionsConfig
from apps.connections.errors import (
    ProviderAuthError,
    ProviderRequestError,
    ProviderUnavailable,
    RateLimited,
    ValidationFailed,
)
from apps.connections.http import HostNotAllowed

from .fakes import Recorder, fixture, json_response, routes

TOKEN = "pfm-test-token-NOT-REAL"


async def no_sleep(_: float) -> None:
    return None


def client(rec: Recorder, token: str = TOKEN, **kw) -> PfmClient:
    config = ConnectionsConfig.from_env({"PFM_JWT_TOKEN": token})
    return PfmClient(config, transport=rec.transport, sleep=no_sleep, **kw)


def test_permissions_are_the_two_values_the_api_accepts() -> None:
    assert PFM_PERMISSIONS == ("posts", "feeds")
    assert pfm.validate_permissions(["posts", "feeds", "posts"]) == ("posts", "feeds")


@pytest.mark.parametrize("bad", [["read", "write"], ["posts", "write"], []])
def test_legacy_permission_names_are_refused(bad: list[str]) -> None:
    with pytest.raises(ValidationFailed):
        pfm.validate_permissions(bad)


async def test_auth_url_requests_posts_and_feeds_and_sends_the_bearer() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        seen["auth"] = request.headers["authorization"]
        return json_response("pfm_auth_url.json")

    rec = Recorder(routes({("POST", "/v1/social-accounts/auth-url"): handler}))
    result = await client(rec).create_auth_url("x", "lumi-profile-1")
    assert seen["body"] == {
        "platform": "x",
        "external_id": "lumi-profile-1",
        "permissions": ["posts", "feeds"],
    }
    assert seen["auth"] == f"Bearer {TOKEN}"
    assert result.url.startswith("https://api.postforme.dev/")


async def test_auth_url_rejects_the_old_read_write_permissions_before_any_request() -> (
    None
):
    rec = Recorder(routes({}))
    with pytest.raises(ValidationFailed):
        await client(rec).create_auth_url("x", "p1", permissions=["read", "write"])
    assert rec.requests == []


async def test_account_parsing_drops_the_platform_tokens() -> None:
    rec = Recorder(
        routes({("GET", "/v1/social-accounts/sa_1"): json_response("pfm_account.json")})
    )
    account = await client(rec).get_social_account("sa_1")
    assert account.connected and account.username == "Ateh"
    text = repr(account) + str(account)
    assert "FAKE-PLATFORM" not in text
    assert not hasattr(account, "access_token") and not hasattr(
        account, "refresh_token"
    )


async def test_list_accounts_has_no_tokens_either() -> None:
    rec = Recorder(
        routes({("GET", "/v1/social-accounts"): json_response("pfm_accounts.json")})
    )
    accounts = await client(rec).list_social_accounts(limit=1)
    assert [a.id for a in accounts] == ["sa_1"]
    assert "FAKE-PLATFORM" not in repr(accounts)
    assert rec.requests[0].url.params["limit"] == "1"


async def test_feed_asks_for_metrics_and_reads_paging_from_meta() -> None:
    rec = Recorder(
        routes(
            {
                ("GET", "/v1/social-account-feeds/sa_1"): json_response(
                    "pfm_feed_x_page1.json"
                )
            }
        )
    )
    page = await client(rec).get_account_feed_page("sa_1", limit=3)
    params = rec.requests[0].url.params
    assert params["expand"] == "metrics" and params["limit"] == "3"
    assert "cursor" not in params
    assert page.has_more and page.cursor == "pgn_next_1" and len(page.items) == 3


async def test_feed_sends_the_cursor_and_stops_when_has_more_is_false() -> None:
    rec = Recorder(
        routes(
            {
                ("GET", "/v1/social-account-feeds/sa_1"): json_response(
                    "pfm_feed_x_page2.json"
                )
            }
        )
    )
    page = await client(rec).get_account_feed_page("sa_1", cursor="pgn_next_1")
    assert rec.requests[0].url.params["cursor"] == "pgn_next_1"
    assert page.has_more is False


async def test_feed_page_size_is_capped() -> None:
    rec = Recorder(
        routes(
            {
                ("GET", "/v1/social-account-feeds/sa_1"): json_response(
                    "pfm_feed_x_page2.json"
                )
            }
        )
    )
    await client(rec).get_account_feed_page("sa_1", limit=5000)
    assert rec.requests[0].url.params["limit"] == "100"


async def test_401_is_a_typed_auth_error_without_the_token_in_it() -> None:
    rec = Recorder(lambda r: httpx.Response(401, json=fixture("pfm_error_401.json")))
    with pytest.raises(ProviderAuthError) as caught:
        await client(rec).list_social_accounts(limit=1)
    assert TOKEN not in str(caught.value)
    assert len(rec.requests) == 1  # auth failures are not retried


async def test_missing_token_fails_before_any_request() -> None:
    rec = Recorder(routes({}))
    with pytest.raises(ProviderUnavailable):
        await client(rec, token="").list_social_accounts()
    assert rec.requests == []


async def test_reads_retry_a_transient_5xx_then_succeed() -> None:
    answers = [
        httpx.Response(503),
        httpx.Response(200, json=fixture("pfm_accounts.json")),
    ]
    rec = Recorder(lambda r: answers.pop(0))
    accounts = await client(rec).list_social_accounts(limit=1)
    assert len(accounts) == 1 and len(rec.requests) == 2


async def test_retries_give_up_and_raise_typed_errors() -> None:
    rec = Recorder(lambda r: httpx.Response(500))
    with pytest.raises(ProviderUnavailable):
        await client(rec).list_social_accounts()
    assert len(rec.requests) == 1 + pfm.READ_RETRIES


async def test_429_surfaces_retry_after() -> None:
    rec = Recorder(lambda r: httpx.Response(429, headers={"retry-after": "7"}))
    with pytest.raises(RateLimited) as caught:
        await client(rec).create_auth_url("x", "p1")
    assert caught.value.retry_after_seconds == 7.0
    assert len(rec.requests) == 1  # a POST is never retried


async def test_non_json_and_wrong_shape_are_request_errors() -> None:
    rec = Recorder(lambda r: httpx.Response(200, text="<html>"))
    with pytest.raises(ProviderRequestError):
        await client(rec).list_social_accounts()
    rec2 = Recorder(lambda r: httpx.Response(200, json={"data": "nope", "meta": {}}))
    with pytest.raises(ProviderRequestError):
        await client(rec2).get_account_feed_page("sa_1")


async def test_only_the_pfm_host_is_reachable() -> None:
    rec = Recorder(routes({}))
    c = client(rec)
    with pytest.raises(HostNotAllowed):
        await c._http.request("GET", "https://evil.example/v1/social-accounts")
    assert rec.requests == []


async def test_local_limiter_is_applied_before_each_call() -> None:
    now = [0.0]
    slept: list[float] = []

    async def sleep(s: float) -> None:
        slept.append(s)
        now[0] += s

    limiter = SlidingWindowLimiter(
        per_second=2, per_minute=40, clock=lambda: now[0], sleep=sleep, provider="pfm"
    )
    rec = Recorder(lambda r: httpx.Response(200, json=fixture("pfm_accounts.json")))
    c = client(rec, limiter=limiter)
    for _ in range(3):
        await c.list_social_accounts(limit=1)
    assert len(slept) == 1 and len(rec.requests) == 3
