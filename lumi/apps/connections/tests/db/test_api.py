"""``/api/v1/connections`` over the real Postgres, with mocked providers and no network."""

from __future__ import annotations

from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from django.db import connection
from rest_framework.test import APIClient

from apps.accounts.models import AuthToken
from apps.connections import accounts
from apps.connections.models import (
    AccountStatus,
    ConnectedAccount,
    OAuthState,
)
from apps.connections.providers.registry import build_provider
from apps.connections.tests.fakes import Recorder, json_response, routes

FRONT = "http://localhost:5173"
META_ENV = {"META_APP_ID": "app-1", "META_APP_SECRET": "sec-1"}
LINKEDIN_ENV = {"LINKEDIN_CLIENT_ID": "li-id", "LINKEDIN_CLIENT_SECRET": "li-sec"}
X_ENV = {"X_CLIENT_ID": "x-id", "X_CLIENT_SECRET": "x-sec"}
PFM_ENV = {"PFM_JWT_TOKEN": "pfm-FAKE-JWT"}
ALL_ENV = {**META_ENV, **LINKEDIN_ENV, **X_ENV, **PFM_ENV}
SECRET_STRINGS = (
    "meta-page1-FAKE",
    "meta-long-FAKE",
    "li-access-FAKE",
    "FAKE-PLATFORM",
)

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def wiring(settings, monkeypatch):
    settings.ROOT_URLCONF = "apps.connections.tests.db.urls"
    for name in (*ALL_ENV, "X_LIVE_ENABLED", "PUBLIC_BASE_URL", "FRONTEND_URL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("FRONTEND_URL", FRONT)


@pytest.fixture
def env(monkeypatch):
    def apply(values: dict[str, str]) -> None:
        for key, value in values.items():
            monkeypatch.setenv(key, value)

    return apply


@pytest.fixture
def providers(monkeypatch):
    """Route provider and PFM calls to mock handlers. Returns the recorders by name."""
    recorders: dict[str, list[Recorder]] = {}
    handlers: dict[str, object] = {}

    def make(name: str):
        rec = Recorder(handlers.get(name) or (lambda r: httpx.Response(500)))
        recorders.setdefault(name, []).append(rec)
        return build_provider(name, accounts.get_config(), transport=rec.transport)

    def make_pfm():
        from apps.connections.clients.pfm import PfmClient

        rec = Recorder(handlers.get("pfm") or (lambda r: httpx.Response(500)))
        recorders.setdefault("pfm", []).append(rec)

        async def no_sleep(_: float) -> None:
            return None

        return PfmClient(accounts.get_config(), transport=rec.transport, sleep=no_sleep)

    monkeypatch.setattr(accounts, "make_provider", make)
    monkeypatch.setattr(accounts, "make_pfm", make_pfm)

    class Wiring:
        def on(self, name: str, table: dict) -> None:
            handlers[name] = routes(table)

        def requests(self, name: str) -> list:
            return [r for rec in recorders.get(name, []) for r in rec.requests]

    return Wiring()


def client_for(user) -> APIClient:
    _, key = AuthToken.issue(user)
    client = APIClient(raise_request_exception=False)
    client.credentials(HTTP_AUTHORIZATION=f"Token {key}")
    return client


@pytest.fixture
def api(user) -> APIClient:
    return client_for(user)


def connect(api, provider: str, **body):
    return api.post(f"/api/v1/connections/{provider}/connect", body, format="json")


def state_of(url: str) -> str:
    return parse_qs(urlsplit(url).query)["state"][0]


def callback(name: str, **params):
    # Deliberately a client with no credentials: the browser redirect has no Token header.
    return APIClient().get(f"/api/v1/connections/{name}/callback", params)


def location(response) -> tuple[str, dict[str, list[str]]]:
    parts = urlsplit(response["Location"])
    return f"{parts.scheme}://{parts.netloc}{parts.path}", parse_qs(parts.query)


META_TABLE = {
    ("GET", "/v26.0/oauth/access_token"): lambda r: json_response(
        "meta_long_token.json"
        if r.url.params.get("grant_type")
        else "meta_short_token.json"
    ),
    ("GET", "/v26.0/me/accounts"): json_response("meta_accounts.json"),
    ("DELETE", "/v26.0/me/permissions"): httpx.Response(200, json={"success": True}),
}
LINKEDIN_TABLE = {
    ("POST", "/oauth/v2/accessToken"): json_response("linkedin_token.json"),
    ("GET", "/v2/userinfo"): json_response("linkedin_userinfo.json"),
}


# --- connect -----------------------------------------------------------------


def test_every_route_needs_the_token_except_the_callback(env) -> None:
    anonymous = APIClient()
    for method, path in [
        ("post", "/api/v1/connections/meta/connect"),
        ("get", "/api/v1/connections/meta/status"),
        ("delete", "/api/v1/connections/meta"),
    ]:
        response = getattr(anonymous, method)(path)
        assert response.status_code == 401, path
        assert response.json()["error"]["code"] == "unauthenticated"
    assert anonymous.get("/api/v1/connections/meta/callback").status_code == 302


def test_unknown_provider_is_404_and_google_is_not_implemented_yet(api) -> None:
    assert connect(api, "myspace").status_code == 404
    response = connect(api, "google")
    assert response.status_code == 501
    assert response.json()["error"]["code"] == "connections.not_implemented"
    assert api.get("/api/v1/connections/myspace/status").status_code == 404


def test_missing_app_keys_answer_503_with_the_variable_names(api) -> None:
    response = connect(api, "meta")
    assert response.status_code == 503
    error = response.json()["error"]
    assert error["code"] == "not_configured"
    assert error["details"]["env_vars"] == ["META_APP_ID", "META_APP_SECRET"]


def test_x_stays_off_without_the_switch_and_stores_no_state(api, env) -> None:
    env(X_ENV)
    response = connect(api, "x")
    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "connections.live_disabled"
    assert error["details"]["env_vars"] == ["X_LIVE_ENABLED"]
    assert OAuthState.objects.count() == 0


def test_connect_returns_json_with_the_authorize_url_and_stores_the_state(
    api, env, profile
) -> None:
    env(META_ENV)
    response = connect(api, "meta", profile_id=profile.pk)
    assert response.status_code == 200
    url = response.json()["authorize_url"]
    parts = urlsplit(url)
    assert parts.netloc == "www.facebook.com"
    row = OAuthState.objects.get(state=state_of(url))
    assert row.provider == "meta" and row.social_profile_id == profile.pk


def test_connect_with_a_foreign_profile_is_404(api, env, other_user) -> None:
    from apps.profiles.models import SocialHandle, SocialProfile

    env(META_ENV)
    handle = SocialHandle.objects.create(platform="x", handle_normalized="theirs")
    theirs = SocialProfile.objects.create(user=other_user, handle=handle)
    response = connect(api, "meta", profile_id=theirs.pk)
    assert response.status_code == 404
    assert OAuthState.objects.count() == 0


def test_connect_validates_the_body(api, env) -> None:
    env(META_ENV)
    response = connect(api, "meta", profile_id="abc")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "validation_error"


def test_pfm_connect_needs_the_platform_and_returns_the_pfm_url(
    api, env, providers, user
) -> None:
    env(PFM_ENV)
    assert connect(api, "pfm").status_code == 400
    seen: dict = {}

    def auth_url(request: httpx.Request) -> httpx.Response:
        seen["body"] = request.content
        return json_response("pfm_auth_url.json")

    providers.on("pfm", {("POST", "/v1/social-accounts/auth-url"): auth_url})
    response = connect(api, "pfm", platform="x")
    assert response.status_code == 200
    assert response.json()["authorize_url"].startswith("https://api.postforme.dev/")
    assert f"lumi-user-{user.pk}".encode() in seen["body"]


def test_pfm_upstream_failure_is_a_502_without_the_provider_text(
    api, env, providers
) -> None:
    env(PFM_ENV)
    providers.on(
        "pfm",
        {
            ("POST", "/v1/social-accounts/auth-url"): httpx.Response(
                503, text="secret upstream detail"
            )
        },
    )
    response = connect(api, "pfm", platform="x")
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "upstream_error"
    assert "secret" not in response.content.decode()


# --- callback ----------------------------------------------------------------


def start_meta(api, env, providers, **body) -> str:
    env(META_ENV)
    providers.on("meta", META_TABLE)
    return state_of(connect(api, "meta", **body).json()["authorize_url"])


def test_meta_callback_stores_the_pages_and_redirects_to_the_frontend(
    api, env, providers, user
) -> None:
    state = start_meta(api, env, providers)
    response = callback("meta", code="c0de", state=state)
    assert response.status_code == 302
    where, query = location(response)
    assert where == f"{FRONT}/" and query == {"connected": ["meta"]}
    assert response["Cache-Control"] == "no-store"
    rows = ConnectedAccount.objects.filter(user=user, provider="meta").order_by(
        "external_account_id"
    )
    # Page 1003 has no token, so it is skipped. Page 1002 is read-only.
    assert [r.external_account_id for r in rows] == ["1001", "1002"]
    assert [r.status for r in rows] == [AccountStatus.ACTIVE, AccountStatus.LIMITED]
    assert rows[0].platform == "facebook" and rows[0].display_name == "Pagina Uno"
    assert rows[0].access_token == "meta-page1-FAKE" and rows[0].expires_at is None


def test_tokens_are_ciphertext_at_rest_and_never_in_any_response(
    api, env, providers
) -> None:
    state = start_meta(api, env, providers)
    callback("meta", code="c0de", state=state)
    with connection.cursor() as cursor:
        cursor.execute("SELECT access_token FROM connected_accounts")
        raw = [r[0] for r in cursor.fetchall()]
    assert raw and all("FAKE" not in value for value in raw)
    status = api.get("/api/v1/connections/meta/status")
    body = status.content.decode()
    assert status.status_code == 200
    assert not any(secret in body for secret in SECRET_STRINGS)
    assert "access_token" not in body and "refresh_token" not in body


def test_a_state_cannot_be_replayed(api, env, providers) -> None:
    state = start_meta(api, env, providers)
    assert "connected" in location(callback("meta", code="c0de", state=state))[1]
    second = callback("meta", code="c0de", state=state)
    assert location(second)[1] == {"error": ["connections.state_invalid"]}
    assert ConnectedAccount.objects.count() == 2


def test_a_state_of_another_provider_does_not_burn_and_does_not_connect(
    api, env, providers
) -> None:
    state = start_meta(api, env, providers)
    env(LINKEDIN_ENV)
    providers.on("linkedin", LINKEDIN_TABLE)
    wrong = callback("linkedin", code="c0de", state=state)
    assert location(wrong)[1] == {"error": ["connections.state_invalid"]}
    assert OAuthState.objects.get(state=state).consumed_at is None
    assert ConnectedAccount.objects.count() == 0


@pytest.mark.parametrize(
    "params",
    [{}, {"code": "c0de"}, {"state": "nope", "code": "c0de"}],
)
def test_bad_callbacks_redirect_with_an_error_and_never_a_500(params, env) -> None:
    env(META_ENV)
    response = callback("meta", **params)
    assert response.status_code == 302
    assert location(response)[1]["error"] == ["connections.state_invalid"]


def test_user_denial_burns_the_state_and_sends_access_denied(
    api, env, providers
) -> None:
    state = start_meta(api, env, providers)
    response = callback("meta", error="access_denied", state=state)
    assert location(response)[1] == {"error": ["connections.access_denied"]}
    assert OAuthState.objects.get(state=state).consumed_at is not None


def test_provider_text_never_reaches_the_redirect(api, env, providers) -> None:
    state = start_meta(api, env, providers)
    providers.on(
        "meta",
        {
            ("GET", "/v26.0/oauth/access_token"): httpx.Response(
                500, text="boom-secret-detail"
            )
        },
    )
    response = callback("meta", code="c0de", state=state)
    assert location(response)[1] == {"error": ["upstream_error"]}
    assert "boom" not in response["Location"]


def test_redirect_after_cannot_leave_the_frontend(api, env, providers) -> None:
    state = start_meta(api, env, providers, redirect_after="https://evil.example/x")
    where, _ = location(callback("meta", code="c0de", state=state))
    assert where == f"{FRONT}/"
    state = start_meta(api, env, providers, redirect_after="/settings/connections")
    where, query = location(callback("meta", code="c0de", state=state))
    assert where == f"{FRONT}/settings/connections" and "connected" in query


def test_linkedin_links_the_single_account_to_the_profile(
    api, env, providers, profile
) -> None:
    env(LINKEDIN_ENV)
    providers.on("linkedin", LINKEDIN_TABLE)
    state = state_of(
        connect(api, "linkedin", profile_id=profile.pk).json()["authorize_url"]
    )
    callback("linkedin", code="c0de", state=state)
    row = ConnectedAccount.objects.get(provider="linkedin")
    assert row.social_profile_id == profile.pk
    assert row.expires_at is not None
    assert row.access_token == "li-access-FAKE"


def test_reconnecting_updates_the_same_row(api, env, providers) -> None:
    for _ in range(2):
        state = start_meta(api, env, providers)
        callback("meta", code="c0de", state=state)
    assert ConnectedAccount.objects.filter(provider="meta").count() == 2


def test_an_account_of_another_user_is_refused_and_left_untouched(
    api, env, providers, other_user
) -> None:
    ConnectedAccount.objects.create(
        user=other_user,
        provider="meta",
        external_account_id="1001",
        access_token="theirs",
        display_name="Theirs",
    )
    state = start_meta(api, env, providers)
    response = callback("meta", code="c0de", state=state)
    assert location(response)[1] == {"error": ["connections.account_taken"]}
    mine = ConnectedAccount.objects.get(provider="meta", external_account_id="1001")
    assert mine.user_id == other_user.pk and mine.access_token == "theirs"
    # The whole grant is rolled back, so page 1002 is not stored either.
    assert ConnectedAccount.objects.count() == 1


def test_pfm_callback_names_no_user_and_only_redirects(env) -> None:
    env(PFM_ENV)
    ok = callback("pfm", provider="x", isSuccess="true", accountIds="sa_1")
    assert location(ok)[1] == {"connected": ["pfm"]}
    failed = callback("pfm", isSuccess="false", error="External Id already exists")
    assert location(failed)[1] == {"error": ["connections.pfm_failed"]}
    assert "External" not in failed["Location"]


# --- status ------------------------------------------------------------------


def test_status_of_a_provider_with_no_accounts(api) -> None:
    body = api.get("/api/v1/connections/linkedin/status").json()
    assert body == {
        "provider": "linkedin",
        "configured": False,
        "connected": False,
        "stale": False,
        "accounts": [],
    }


def test_status_lists_only_my_accounts(api, env, providers, other_user) -> None:
    ConnectedAccount.objects.create(
        user=other_user, provider="meta", external_account_id="9", display_name="X"
    )
    state = start_meta(api, env, providers)
    callback("meta", code="c0de", state=state)
    body = api.get("/api/v1/connections/meta/status").json()
    assert body["configured"] and body["connected"] and not body["stale"]
    assert [a["id"] for a in body["accounts"]] == ["1001", "1002"]


PFM_ACCOUNTS = {
    ("GET", "/v1/social-accounts"): json_response("pfm_accounts.json"),
}


def test_pfm_status_syncs_accounts_by_external_id_and_hides_their_tokens(
    api, env, providers, user
) -> None:
    env(PFM_ENV)
    providers.on("pfm", PFM_ACCOUNTS)
    response = api.get("/api/v1/connections/pfm/status")
    body = response.json()
    assert body["connected"] and body["accounts"][0]["platform"] == "x"
    assert body["accounts"][0]["handle"] == "Ateh"
    assert "FAKE-PLATFORM" not in response.content.decode()
    sent = providers.requests("pfm")[0]
    assert sent.url.params["external_id"] == f"lumi-user-{user.pk}"
    row = ConnectedAccount.objects.get(provider="pfm")
    assert row.access_token == "" and row.external_account_id == "sa_1"


def test_pfm_status_marks_missing_accounts_revoked_and_survives_an_outage(
    api, env, providers, user
) -> None:
    env(PFM_ENV)
    ConnectedAccount.objects.create(
        user=user, provider="pfm", external_account_id="gone", platform="x"
    )
    providers.on("pfm", PFM_ACCOUNTS)
    api.get("/api/v1/connections/pfm/status")
    assert (
        ConnectedAccount.objects.get(external_account_id="gone").status
        == AccountStatus.REVOKED
    )
    providers.on("pfm", {("GET", "/v1/social-accounts"): httpx.Response(503)})
    body = api.get("/api/v1/connections/pfm/status").json()
    assert body["stale"] is True and len(body["accounts"]) == 2


# --- disconnect --------------------------------------------------------------


def test_disconnect_revokes_remotely_and_deletes_the_tokens(
    api, env, providers, other_user
) -> None:
    theirs = ConnectedAccount.objects.create(
        user=other_user, provider="meta", external_account_id="77", access_token="t"
    )
    state = start_meta(api, env, providers)
    callback("meta", code="c0de", state=state)
    response = api.delete("/api/v1/connections/meta")
    assert response.status_code == 200
    assert response.json() == {
        "provider": "meta",
        "disconnected": 2,
        "remote_revoked": 2,
    }
    assert not ConnectedAccount.objects.filter(user__email="owner@example.com")
    assert ConnectedAccount.objects.filter(pk=theirs.pk).exists()


def test_disconnect_deletes_even_when_the_provider_is_down(api, env, providers) -> None:
    state = start_meta(api, env, providers)
    callback("meta", code="c0de", state=state)
    providers.on("meta", {("DELETE", "/v26.0/me/permissions"): httpx.Response(503)})
    body = api.delete("/api/v1/connections/meta").json()
    assert body["disconnected"] == 2 and body["remote_revoked"] == 0
    assert ConnectedAccount.objects.count() == 0


def test_disconnect_one_account_and_404_for_unknown_or_foreign(
    api, env, providers, other_user
) -> None:
    ConnectedAccount.objects.create(
        user=other_user, provider="meta", external_account_id="77"
    )
    state = start_meta(api, env, providers)
    callback("meta", code="c0de", state=state)
    assert api.delete("/api/v1/connections/meta?account_id=77").status_code == 404
    assert api.delete("/api/v1/connections/meta?account_id=nope").status_code == 404
    assert api.delete("/api/v1/connections/meta?account_id=1002").status_code == 200
    left = ConnectedAccount.objects.filter(user__email="owner@example.com")
    assert [r.external_account_id for r in left] == ["1001"]


def test_pfm_disconnect_calls_pfm_for_each_account(api, env, providers) -> None:
    env(PFM_ENV)
    providers.on(
        "pfm",
        {
            **PFM_ACCOUNTS,
            ("POST", "/v1/social-accounts/sa_1/disconnect"): json_response(
                "pfm_account.json"
            ),
        },
    )
    api.get("/api/v1/connections/pfm/status")
    body = api.delete("/api/v1/connections/pfm").json()
    assert body["disconnected"] == 1 and body["remote_revoked"] == 1
    assert ConnectedAccount.objects.count() == 0


# --- refresh -----------------------------------------------------------------


def expiring(user, provider="meta", *, days=2, **extra):
    from django.utils import timezone

    return ConnectedAccount.objects.create(
        user=user,
        provider=provider,
        external_account_id=f"{provider}-1",
        access_token="old-access",
        refresh_token=extra.pop("refresh_token", ""),
        expires_at=timezone.now() + timedelta(days=days),
        **extra,
    )


def test_refresh_due_renews_a_token_inside_the_window(env, providers, user) -> None:
    env(META_ENV)
    providers.on("meta", META_TABLE)
    row = expiring(user)
    safe = expiring(user, "linkedin", days=30)
    assert accounts.refresh_due() == {"refreshed": 1}
    row.refresh_from_db()
    safe.refresh_from_db()
    assert row.access_token == "meta-long-FAKE" and row.last_refreshed_at is not None
    assert row.expires_at > safe.expires_at - timedelta(days=40)
    assert safe.access_token == "old-access"


def test_refresh_never_touches_x_while_it_is_switched_off(env, providers, user) -> None:
    env(X_ENV)
    row = expiring(user, "x", refresh_token="r")
    assert accounts.refresh_due() == {"skipped_live_disabled": 1}
    assert providers.requests("x") == []
    row.refresh_from_db()
    assert row.status == AccountStatus.ACTIVE


def test_refresh_without_a_refresh_token_flags_the_error_and_expires_when_late(
    env, providers, user
) -> None:
    env(LINKEDIN_ENV)
    soon = expiring(user, "linkedin", days=2)
    assert accounts.refresh_due() == {"needs_reconnect": 1}
    soon.refresh_from_db()
    assert soon.status == AccountStatus.ACTIVE and soon.last_error
    soon.expires_at = soon.expires_at - timedelta(days=3)
    soon.save()
    accounts.refresh_due()
    soon.refresh_from_db()
    assert soon.status == AccountStatus.EXPIRED


def test_refresh_keeps_the_account_when_the_provider_is_down(
    env, providers, user
) -> None:
    env(META_ENV)
    providers.on("meta", {("GET", "/v26.0/oauth/access_token"): httpx.Response(503)})
    row = expiring(user)
    assert accounts.refresh_due() == {"retry_later": 1}
    row.refresh_from_db()
    assert row.status == AccountStatus.ACTIVE and row.access_token == "old-access"


def test_refresh_skips_pfm_and_revoked_rows(env, providers, user) -> None:
    env({**META_ENV, **PFM_ENV})
    expiring(user, "pfm")
    expiring(user, "meta", status=AccountStatus.REVOKED)
    assert accounts.refresh_due() == {}
