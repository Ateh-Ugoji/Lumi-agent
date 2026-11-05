"""The routes as ARCHITECT mounts them in ``config/urls.py``, with the real ROOT_URLCONF."""

from __future__ import annotations

import pytest
from django.urls import reverse

from .test_api import client_for

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize(
    ("name", "kwargs", "path"),
    [
        (
            "connections-connect",
            {"provider": "meta"},
            "/api/v1/connections/meta/connect",
        ),
        (
            "connections-callback",
            {"provider": "meta"},
            "/api/v1/connections/meta/callback",
        ),
        ("connections-status", {"provider": "pfm"}, "/api/v1/connections/pfm/status"),
        ("connections-provider", {"provider": "x"}, "/api/v1/connections/x"),
        (
            "connections-status",
            {"provider": "google"},
            "/api/v1/connections/google/status",
        ),
        ("handles-search", {}, "/api/v1/handles/search"),
        ("handles-saved", {}, "/api/v1/handles/saved"),
        ("handles-select", {}, "/api/v1/handles/select"),
        ("handles-stats", {}, "/api/v1/handles/stats"),
        ("publish", {}, "/api/v1/publish"),
    ],
)
def test_every_route_is_mounted_under_api_v1(name, kwargs, path) -> None:
    assert reverse(name, kwargs=kwargs) == path


def test_the_default_urlconf_serves_status_and_handles(user, monkeypatch) -> None:
    for var in ("META_APP_ID", "META_APP_SECRET", "XPOZ_API_KEY", "XPOZ_LIVE_ENABLED"):
        monkeypatch.delenv(var, raising=False)
    api = client_for(user)
    status = api.get("/api/v1/connections/meta/status")
    assert status.status_code == 200
    assert status.json()["configured"] is False and status.json()["connected"] is False
    assert api.get("/api/v1/handles/stats").status_code == 200
    connect = api.post("/api/v1/connections/meta/connect", {}, format="json")
    assert connect.status_code == 503
    assert connect.json()["error"]["code"] == "not_configured"


def test_the_callback_needs_a_token_and_the_api_no_longer_redirects(client) -> None:
    """The provider redirects to a frontend page. The API route only takes the authenticated POST."""
    assert client.post("/api/v1/connections/meta/callback", {}).status_code == 401
    assert client.get(
        "/api/v1/connections/meta/callback", {"code": "x", "state": "y"}
    ).status_code in (401, 405)


def test_publish_is_mounted_and_guarded_in_the_default_urlconf(user, client) -> None:
    assert (
        client.post("/api/v1/publish", {}, content_type="application/json").status_code
        == 401
    )
    api = client_for(user)
    empty = api.post("/api/v1/publish", {}, format="json")
    assert empty.status_code == 400
    assert empty.json()["error"]["code"] == "validation_error"


def test_google_status_is_served_by_the_default_urlconf(user, monkeypatch) -> None:
    for var in ("GOOGLE_OAUTH_CLIENT_ID", "GOOGLE_OAUTH_CLIENT_SECRET"):
        monkeypatch.delenv(var, raising=False)
    body = client_for(user).get("/api/v1/connections/google/status").json()
    assert body["provider"] == "google"
    assert body["configured"] is False and body["connected"] is False
    assert body["details"] == {}
