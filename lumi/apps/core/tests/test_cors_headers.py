"""A browser blocks any request whose headers the preflight answer did not allow."""

import pytest
from django.test import Client

ORIGIN = "http://localhost:3010"


def preflight(headers: str):
    return Client().options(
        "/api/v1/publish",
        HTTP_ORIGIN=ORIGIN,
        HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST",
        HTTP_ACCESS_CONTROL_REQUEST_HEADERS=headers,
    )


def allowed(response) -> set[str]:
    raw = response.headers.get("access-control-allow-headers", "")
    return {h.strip().lower() for h in raw.split(",") if h.strip()}


def test_the_real_publish_can_send_its_idempotency_key() -> None:
    response = preflight("authorization,content-type,idempotency-key")
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == ORIGIN
    assert "idempotency-key" in allowed(response)


@pytest.mark.parametrize("header", ["authorization", "content-type", "accept"])
def test_the_headers_every_call_sends_stay_allowed(header) -> None:
    assert header in allowed(preflight(header))


def test_an_unknown_origin_gets_no_cors_headers() -> None:
    response = Client().options(
        "/api/v1/publish",
        HTTP_ORIGIN="http://evil.example",
        HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST",
        HTTP_ACCESS_CONTROL_REQUEST_HEADERS="idempotency-key",
    )
    assert "access-control-allow-origin" not in response.headers
