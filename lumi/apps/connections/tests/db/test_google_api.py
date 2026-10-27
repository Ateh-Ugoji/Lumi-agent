# ruff: noqa: F401, F811  (fixtures imported from test_api)
"""Google connect flow and the MCP stores over the real Postgres. No network."""

from __future__ import annotations

from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from asgiref.sync import async_to_sync
from django.db import connection

from apps.connections import accounts
from apps.connections.mcp.gateway import McpGatewayCore, PendingWrite
from apps.connections.mcp.google import GoogleOAuth
from apps.connections.models import McpAuthAccount, McpPendingWrite, OAuthState
from apps.connections.providers.base import TokenSet
from apps.connections.stores import DjangoMcpStore, save_google_tokens
from apps.connections.tests.mcp.fakes import FakeTransport

from .test_api import (
    FRONT,
    api,
    callback,
    client_for,
    connect,
    env,
    location,
    state_of,
    wiring,
)

pytestmark = pytest.mark.django_db

GOOGLE_ENV = {"GOOGLE_OAUTH_CLIENT_ID": "g-id", "GOOGLE_OAUTH_CLIENT_SECRET": "g-sec"}
SECRETS = ("ya29-FAKE", "1//RT-FAKE", "g-sec")


@pytest.fixture
def google(monkeypatch):
    """Route Google's token and revoke endpoints to a recorder. Returns it."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == "/token":
            body = request.content.decode()
            if "code=bad" in body:
                return httpx.Response(400, json={"error": "invalid_grant"})
            return httpx.Response(
                200,
                json={
                    "access_token": "ya29-FAKE",
                    "refresh_token": "1//RT-FAKE",
                    "expires_in": 3600,
                    "scope": "https://www.googleapis.com/auth/drive.file",
                },
            )
        if request.url.path == "/revoke":
            return httpx.Response(200, json={})
        raise AssertionError(f"unexpected {request.url}")

    monkeypatch.setattr(
        accounts,
        "make_google",
        lambda: GoogleOAuth(
            accounts.get_config(), transport=httpx.MockTransport(handler)
        ),
    )
    return seen


def start(api, env):
    env(GOOGLE_ENV)
    return state_of(connect(api, "google").json()["authorize_url"])


def test_status_before_connecting(api, env) -> None:
    body = api.get("/api/v1/connections/google/status").json()
    assert body["provider"] == "google" and body["configured"] is False
    assert body["connected"] is False and body["accounts"] == []
    env(GOOGLE_ENV)
    assert api.get("/api/v1/connections/google").json()["configured"] is True


def test_connect_returns_the_consent_url_with_offline_access_and_pkce(api, env) -> None:
    env(GOOGLE_ENV)
    response = connect(api, "google", redirect_after="/settings")
    assert response.status_code == 200
    url = response.json()["authorize_url"]
    q = {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}
    assert urlsplit(url).netloc == "accounts.google.com"
    assert q["access_type"] == "offline" and q["prompt"] == "consent"
    assert q["code_challenge_method"] == "S256"
    assert q["redirect_uri"].endswith("/api/v1/connections/google/callback")
    row = OAuthState.objects.get(state=q["state"])
    assert row.provider == "google" and row.redirect_after == "/settings"
    assert "g-sec" not in url


def test_the_redirect_uri_can_be_overridden_with_the_env_var(api, env) -> None:
    env({**GOOGLE_ENV, "GOOGLE_OAUTH_REDIRECT_URI": "https://app.example.com/cb"})
    url = connect(api, "google").json()["authorize_url"]
    assert parse_qs(urlsplit(url).query)["redirect_uri"] == [
        "https://app.example.com/cb"
    ]


def test_callback_stores_the_grant_and_redirects_without_any_token(
    api, env, google, user
) -> None:
    state = start(api, env)
    response = callback("google", code="c0de", state=state)
    assert response.status_code == 302
    where, query = location(response)
    assert where == f"{FRONT}/" and query == {"connected": ["google"]}
    assert not any(s in response["Location"] for s in SECRETS)
    row = McpAuthAccount.objects.get(user=user, account="google")
    assert row.access_token == "ya29-FAKE" and row.refresh_token == "1//RT-FAKE"
    verifier = parse_qs(google[0].content.decode())["code_verifier"][0]
    assert len(verifier) >= 43
    body = api.get("/api/v1/connections/google/status").json()
    assert body["connected"] is True and body["stale"] is False
    assert body["details"]["has_refresh_token"] is True
    assert body["details"]["scopes"] == ["https://www.googleapis.com/auth/drive.file"]
    assert not any(s in str(body) for s in SECRETS)


def test_tokens_are_ciphertext_at_rest(api, env, google, user) -> None:
    callback("google", code="c0de", state=start(api, env))
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT access_token, refresh_token FROM mcp_auth_accounts WHERE user_id = %s",
            [user.pk],
        )
        raw = " ".join(cursor.fetchone())
    assert "ya29-FAKE" not in raw and "1//RT-FAKE" not in raw


def test_connecting_again_replaces_the_grant(api, env, google, user) -> None:
    callback("google", code="c0de", state=start(api, env))
    callback("google", code="c0de", state=start(api, env))
    assert McpAuthAccount.objects.filter(user=user, account="google").count() == 1


@pytest.mark.parametrize(
    ("params", "error"),
    [
        ({"error": "access_denied"}, "connections.access_denied"),
        ({"code": "c0de"}, "connections.state_invalid"),
        ({"code": "c0de", "state": "nope"}, "connections.state_invalid"),
    ],
)
def test_bad_google_callbacks_redirect_with_an_error(
    params, error, env, google
) -> None:
    env(GOOGLE_ENV)
    response = callback("google", **params)
    assert response.status_code == 302
    assert location(response)[1] == {"error": [error]}


def test_denied_consent_burns_the_state_and_a_replay_fails(api, env, google) -> None:
    state = start(api, env)
    callback("google", error="access_denied", state=state)
    replay = callback("google", code="c0de", state=state)
    assert location(replay)[1] == {"error": ["connections.state_invalid"]}
    assert McpAuthAccount.objects.count() == 0


def test_a_rejected_code_redirects_with_an_error_and_stores_nothing(
    api, env, google
) -> None:
    state = start(api, env)
    response = callback("google", code="bad", state=state)
    assert location(response)[1] == {"error": ["connections.provider_rejected"]}
    assert McpAuthAccount.objects.count() == 0


def test_a_grant_without_a_refresh_token_is_stale_once_expired(api, user) -> None:
    McpAuthAccount.objects.create(
        user=user,
        account="google",
        access_token="a",
        expires_at=accounts.datetime.now(accounts.UTC) - timedelta(minutes=1),
    )
    body = api.get("/api/v1/connections/google/status").json()
    assert body["connected"] is False and body["stale"] is True


def test_disconnect_revokes_deletes_the_grant_and_parked_writes(
    api, env, google, user, profile, other_user
) -> None:
    callback("google", code="c0de", state=start(api, env))
    McpAuthAccount.objects.create(user=other_user, account="google", access_token="t")
    park(user, profile)
    response = api.delete("/api/v1/connections/google")
    assert response.json() == {
        "provider": "google",
        "disconnected": 1,
        "remote_revoked": 1,
    }
    assert [r.url.path for r in google][-1] == "/revoke"
    assert not McpAuthAccount.objects.filter(user=user).exists()
    assert McpAuthAccount.objects.filter(user=other_user).exists()
    assert not McpPendingWrite.objects.exists()
    assert api.delete("/api/v1/connections/google").json()["disconnected"] == 0


def test_disconnect_deletes_even_when_google_is_down(
    api, env, google, user, monkeypatch
) -> None:
    callback("google", code="c0de", state=start(api, env))
    monkeypatch.setattr(
        accounts,
        "make_google",
        lambda: GoogleOAuth(
            accounts.get_config(),
            transport=httpx.MockTransport(lambda r: httpx.Response(503)),
        ),
    )
    body = api.delete("/api/v1/connections/google").json()
    assert body["disconnected"] == 1 and body["remote_revoked"] == 0
    assert not McpAuthAccount.objects.filter(user=user).exists()


# --- stores ------------------------------------------------------------------


def park(user, profile, *, title="Plan", expires=None):
    from django.utils import timezone

    write = PendingWrite(
        user_id=user.pk,
        profile_id=profile.pk,
        tool="mcp__gdrive__create_file",
        server_tool="create_file",
        arguments={"title": title},
        summary=f"create {title}",
        expires_at=expires or timezone.now() + timedelta(minutes=30),
    )
    async_to_sync(DjangoMcpStore().park)(write)
    return write


def test_a_parked_write_is_claimed_exactly_once(user, profile) -> None:
    park(user, profile)
    store = DjangoMcpStore()
    first = async_to_sync(store.claim)(profile.pk)
    assert first is not None and first.arguments == {"title": "Plan"}
    assert first.user_id == user.pk and first.server_tool == "create_file"
    assert async_to_sync(store.claim)(profile.pk) is None


def test_a_live_parked_write_is_not_replaced_by_a_different_one(user, profile) -> None:
    first = park(user, profile, title="A")
    from django.utils import timezone

    other = PendingWrite(
        user_id=user.pk,
        profile_id=profile.pk,
        tool=first.tool,
        server_tool=first.server_tool,
        arguments={"title": "B"},
        summary="create B",
        expires_at=timezone.now() + timedelta(minutes=30),
    )
    waiting = async_to_sync(DjangoMcpStore().park)(other)
    assert waiting is not None and waiting.arguments == {"title": "A"}
    assert McpPendingWrite.objects.count() == 1
    claimed = async_to_sync(DjangoMcpStore().claim)(profile.pk)
    assert claimed is not None and claimed.arguments == {"title": "A"}


def test_the_same_write_again_is_stored_and_an_expired_one_is_replaced(
    user, profile
) -> None:
    from django.utils import timezone

    park(user, profile, title="A")
    assert park(user, profile, title="A") is not None  # same write: stored again
    park(user, profile, title="A", expires=timezone.now() - timedelta(minutes=1))
    park(user, profile, title="B")  # the live A is gone: it expired
    claimed = async_to_sync(DjangoMcpStore().claim)(profile.pk)
    assert claimed is not None and claimed.arguments == {"title": "B"}


def test_deleting_the_profile_deletes_its_parked_write(user, profile) -> None:
    park(user, profile)
    profile.delete()
    assert not McpPendingWrite.objects.exists()


def test_owner_of_and_missing_tokens(user, profile) -> None:
    store = DjangoMcpStore()
    assert async_to_sync(store.owner_of)(profile.pk) == user.pk
    assert async_to_sync(store.owner_of)(999999) is None
    assert async_to_sync(store.load_tokens)(user.pk) is None
    McpAuthAccount.objects.create(user=user, account="google")  # empty token
    assert async_to_sync(store.load_tokens)(user.pk) is None


def test_a_refresh_without_a_refresh_token_keeps_the_stored_one(user) -> None:
    save_google_tokens(user.pk, TokenSet(access_token="a1", refresh_token="RT"))
    save_google_tokens(user.pk, TokenSet(access_token="a2"))
    loaded = async_to_sync(DjangoMcpStore().load_tokens)(user.pk)
    assert loaded is not None
    assert loaded.access_token == "a2" and loaded.refresh_token == "RT"


def test_gateway_over_the_real_store_isolates_users(user, other_user, profile) -> None:
    from apps.connections.mcp.gateway import McpGatewayCore

    save_google_tokens(user.pk, TokenSet(access_token="AT-OWNER"))
    save_google_tokens(other_user.pk, TokenSet(access_token="AT-OTHER"))
    transport = FakeTransport()
    core = _core(transport)
    async_to_sync(core.list_tools)(profile.pk)
    assert {bearer for _, bearer in transport.opened} == {"AT-OWNER"}
    assert isinstance(core, McpGatewayCore)


def _core(transport: FakeTransport) -> McpGatewayCore:
    config = accounts.get_config()
    return McpGatewayCore(DjangoMcpStore(), transport, GoogleOAuth(config), config, {})


def test_a_write_parks_then_runs_once_after_a_yes(user, profile) -> None:
    save_google_tokens(user.pk, TokenSet(access_token="AT-OWNER"))
    transport = FakeTransport()
    core = _core(transport)
    parked = async_to_sync(core.call)(
        profile.pk, "mcp__gdrive__create_file", {"title": "T"}
    )
    assert parked.status == "confirmation_required" and transport.calls == []
    assert McpPendingWrite.objects.filter(social_profile=profile).exists()
    done = async_to_sync(core.resolve_pending)(profile.pk, "yes")
    assert done is not None and done.tool == "mcp__gdrive__create_file"
    assert async_to_sync(core.resolve_pending)(profile.pk, "yes") is None
    assert len([c for c in transport.calls if c[1] == "create_file"]) == 1


def test_a_stranger_cannot_resolve_nothing_for_a_profile_without_a_write(
    user, profile
) -> None:
    core = _core(FakeTransport())
    assert async_to_sync(core.resolve_pending)(profile.pk, "yes") is None


def _lost_google_grant(settings, user) -> None:
    from cryptography.fernet import Fernet

    current = settings.TOKEN_ENCRYPTION_KEY
    settings.TOKEN_ENCRYPTION_KEY = Fernet.generate_key().decode()
    try:
        McpAuthAccount.objects.create(
            user=user, account="google", access_token="a", refresh_token="r"
        )
    finally:
        settings.TOKEN_ENCRYPTION_KEY = current


def test_an_unreadable_google_grant_reads_as_not_connected(api, user, settings) -> None:
    _lost_google_grant(settings, user)
    out = api.get("/api/v1/connections/google/status")
    assert out.status_code == 200
    assert out.json()["connected"] is False
    assert async_to_sync(DjangoMcpStore().load_tokens)(user.pk) is None


def test_connecting_google_again_replaces_an_unreadable_grant(user, settings) -> None:
    _lost_google_grant(settings, user)
    save_google_tokens(user.pk, TokenSet(access_token="new", refresh_token="new-r"))
    row = McpAuthAccount.objects.get(user=user, account="google")
    assert (row.access_token, row.refresh_token) == ("new", "new-r")
