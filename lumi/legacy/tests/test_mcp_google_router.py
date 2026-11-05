"""Google OAuth routes (`app/routers/mcp_google.py`) — hermetic.

Every external hop is patched: the consent page is asserted on its URL
components (never followed), and the code->token exchange is monkeypatched at
the service seam. No secrets are configured, so these tests also prove the
not-configured path answers honestly instead of fabricating a consent URL.
"""

import json
from urllib.parse import parse_qs, urlparse

import pytest

from app.routers import mcp_google
from app.services import mcp as mcp_service


@pytest.fixture(autouse=True)
def clean():
    mcp_service._reset_state()
    mcp_google._states.clear()
    yield
    mcp_service._reset_state()
    mcp_google._states.clear()


def test_router_exposes_the_three_routes():
    paths = sorted(route.path for route in mcp_google.router.routes)
    assert paths == ["/mcp/google/callback", "/mcp/google/connect", "/mcp/google/status"]


async def test_connect_without_client_config_is_honest(monkeypatch):
    from app import config

    settings = config.get_settings()
    monkeypatch.setattr(settings, "google_oauth_client_id", "")
    monkeypatch.setattr(settings, "google_oauth_client_secret", "")

    response = await mcp_google.connect()
    body = json.loads(response.body)
    assert response.status_code == 503  # honest failure, not a fabricated URL
    assert body["error"] == "google_oauth_not_configured"
    assert "GOOGLE_OAUTH_CLIENT_ID" in body["detail"]  # names env vars, no values


async def test_connect_redirects_to_google_with_offline_consent(monkeypatch):
    from app import config

    settings = config.get_settings()
    monkeypatch.setattr(settings, "google_oauth_client_id", "cid-test")
    monkeypatch.setattr(settings, "google_oauth_client_secret", "csecret-test")

    response = await mcp_google.connect()

    location = response.headers["location"]
    parsed = urlparse(location)
    assert response.status_code == 302
    assert parsed.netloc == "accounts.google.com"
    query = parse_qs(parsed.query)
    assert query["client_id"] == ["cid-test"]
    assert query["response_type"] == ["code"]
    assert query["access_type"] == ["offline"]  # refresh token only comes with this
    assert query["prompt"] == ["consent"]  # ...and forced consent on re-connects
    assert query["redirect_uri"] == [settings.google_oauth_redirect_uri]
    scopes = set(query["scope"][0].split(" "))
    # union of every google_oauth connector's scopes (drive.list + docs.create)
    assert "https://www.googleapis.com/auth/drive.readonly" in scopes
    assert "https://www.googleapis.com/auth/drive.file" in scopes
    assert "https://www.googleapis.com/auth/documents" in scopes
    assert query["state"][0] in mcp_google._states  # anti-CSRF state issued


async def test_callback_user_denied(monkeypatch):
    result = await mcp_google.callback(error="access_denied")
    assert result == {"connected": False, "error": "access_denied"}


async def test_callback_rejects_unknown_state(monkeypatch):
    async def should_not_run(code):
        raise AssertionError("no exchange without a valid state")

    monkeypatch.setattr(mcp_service, "exchange_google_code", should_not_run)
    result = await mcp_google.callback(code="c", state="bogus")
    assert result == {"connected": False, "error": "invalid_state"}


async def test_callback_missing_code(monkeypatch):
    result = await mcp_google.callback(state="whatever")
    assert result == {"connected": False, "error": "missing_code"}


async def test_callback_exchanges_code_and_stores_tokens(monkeypatch):
    seen: dict = {}

    async def fake_exchange(code):
        seen["code"] = code
        return {"connected": True, "account": "google", "scopes": "a b"}

    monkeypatch.setattr(mcp_service, "exchange_google_code", fake_exchange)

    mcp_google._states["st"] = 1.0
    result = await mcp_google.callback(code="the-code", state="st")

    assert result["connected"] is True
    assert seen["code"] == "the-code"
    assert "st" not in mcp_google._states  # state is single-use


async def test_status_reports_not_connected(monkeypatch):
    from app import config

    settings = config.get_settings()
    monkeypatch.setattr(settings, "google_oauth_client_id", "")
    monkeypatch.setattr(settings, "google_oauth_client_secret", "")

    async def fake_info():
        return {"connected": False}

    monkeypatch.setattr(mcp_service, "google_token_info", fake_info)
    result = await mcp_google.status()
    assert result == {
        "connected": False,
        "configured": False,  # env vars unset -> the UI explains instead of a dead button
        "connect_path": "/mcp/google/connect",
    }


async def test_status_reports_configured_when_client_env_set(monkeypatch):
    from app import config

    settings = config.get_settings()
    monkeypatch.setattr(settings, "google_oauth_client_id", "test-client-id")
    monkeypatch.setattr(settings, "google_oauth_client_secret", "test-client-secret")

    async def fake_info():
        return {"connected": False}

    monkeypatch.setattr(mcp_service, "google_token_info", fake_info)
    result = await mcp_google.status()
    assert result["configured"] is True  # a boolean only — no values echoed
