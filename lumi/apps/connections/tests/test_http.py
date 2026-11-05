from __future__ import annotations

import httpx
import pytest

from apps.connections.errors import (
    BudgetExceeded,
    ProviderAuthError,
    ProviderRequestError,
    ProviderUnavailable,
    RateLimited,
)
from apps.connections.http import HostNotAllowed, ProviderHttp

from .fakes import Recorder


def client(handler, **kwargs) -> tuple[ProviderHttp, Recorder, list[float]]:
    rec = Recorder(handler)
    slept: list[float] = []

    async def sleep(seconds: float) -> None:
        slept.append(seconds)

    http = ProviderHttp(
        "demo",
        allowed_hosts=frozenset({"api.example.com"}),
        transport=rec.transport,
        sleep=sleep,
        **kwargs,
    )
    return http, rec, slept


@pytest.mark.parametrize(
    ("status", "error"),
    [
        (401, ProviderAuthError),
        (403, ProviderAuthError),
        (402, BudgetExceeded),
        (429, RateLimited),
        (500, ProviderUnavailable),
        (503, ProviderUnavailable),
        (400, ProviderRequestError),
        (404, ProviderRequestError),
    ],
)
async def test_status_maps_to_typed_error(status: int, error: type[Exception]) -> None:
    http, _, _ = client(lambda r: httpx.Response(status, json={"message": "nope"}))
    with pytest.raises(error) as info:
        await http.request("GET", "https://api.example.com/x")
    assert info.value.provider == "demo"


async def test_oauth_invalid_grant_is_an_auth_error() -> None:
    http, _, _ = client(lambda r: httpx.Response(400, json={"error": "invalid_grant"}))
    with pytest.raises(ProviderAuthError):
        await http.request("POST", "https://api.example.com/token")


async def test_rate_limit_carries_retry_after() -> None:
    http, _, _ = client(lambda r: httpx.Response(429, headers={"retry-after": "12"}))
    with pytest.raises(RateLimited) as info:
        await http.request("GET", "https://api.example.com/x")
    assert info.value.retry_after_seconds == 12.0


async def test_host_outside_the_allow_list_sends_nothing() -> None:
    http, rec, _ = client(lambda r: httpx.Response(200, json={}))
    with pytest.raises(HostNotAllowed):
        await http.request("GET", "https://evil.example.org/x")
    assert rec.requests == []


async def test_retries_on_5xx_then_succeeds_and_waits_between_attempts() -> None:
    answers = iter(
        [
            httpx.Response(503),
            httpx.Response(429, headers={"retry-after": "1"}),
            httpx.Response(200, json={"ok": 1}),
        ]
    )
    http, rec, slept = client(lambda r: next(answers))
    response = await http.request("GET", "https://api.example.com/x", retries=2)
    assert response.json() == {"ok": 1}
    assert len(rec.requests) == 3
    assert len(slept) == 2


async def test_no_retry_by_default_so_writes_are_sent_once() -> None:
    http, rec, _ = client(lambda r: httpx.Response(503))
    with pytest.raises(ProviderUnavailable):
        await http.request("POST", "https://api.example.com/x")
    assert len(rec.requests) == 1


async def test_network_error_becomes_unavailable_without_url_or_secret() -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(
            "connect failed for https://api.example.com/x?access_token=SECRET"
        )

    http, _, _ = client(boom)
    with pytest.raises(ProviderUnavailable) as info:
        await http.request(
            "GET", "https://api.example.com/x", params={"access_token": "SECRET"}
        )
    assert "SECRET" not in str(info.value)
    assert "api.example.com" not in str(info.value)
    assert info.value.__cause__ is None


async def test_error_message_uses_provider_text_only_and_is_capped() -> None:
    http, _, _ = client(
        lambda r: httpx.Response(400, json={"error_description": "x" * 500})
    )
    with pytest.raises(ProviderRequestError) as info:
        await http.request("GET", "https://api.example.com/x")
    assert len(str(info.value)) == 200


async def test_redirects_are_not_followed() -> None:
    http, rec, _ = client(
        lambda r: httpx.Response(302, headers={"location": "https://evil.example.org/"})
    )
    response = await http.request("GET", "https://api.example.com/x", check=False)
    assert response.status_code == 302
    assert len(rec.requests) == 1


async def test_a_redirect_is_an_error_by_default_and_is_never_followed() -> None:
    http, rec, _ = client(
        lambda r: httpx.Response(302, headers={"location": "https://evil.example.org/"})
    )
    with pytest.raises(ProviderRequestError) as info:
        await http.request("GET", "https://api.example.com/x")
    assert "evil" not in str(info.value)
    assert len(rec.requests) == 1
