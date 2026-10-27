# ruff: noqa: F811
"""``GET /pfm/status`` only reads. ``POST /pfm/sync`` is the one call that asks Post for Me."""

from __future__ import annotations

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.connections.models import AccountStatus, ConnectedAccount, PfmLink
from apps.connections.tests.db.test_api import (  # noqa: F401  fixtures and helpers
    META_ENV,
    PFM_ACCOUNTS,
    PFM_ENV,
    api,
    client_for,
    env,
    lost_row,
    providers,
    wiring,
)

pytestmark = pytest.mark.django_db

WRITES = ("INSERT", "UPDATE", "DELETE")


def writes(queries) -> list[str]:
    """Writes by this app. The auth layer stamps ``last_used_at`` on the token on every request."""
    found = [q["sql"] for q in queries if q["sql"].lstrip().upper().startswith(WRITES)]
    return [sql[:80] for sql in found if "auth_tokens" not in sql]


@pytest.fixture
def linked(env, providers, user):
    env(PFM_ENV)
    PfmLink.objects.create(user=user, external_id="lumi-link-1")
    providers.on("pfm", PFM_ACCOUNTS)
    return user


def test_status_never_calls_pfm_and_never_writes(api, linked, providers) -> None:
    with CaptureQueriesContext(connection) as ctx:
        body = api.get("/api/v1/connections/pfm/status").json()
    assert providers.requests("pfm") == []
    assert writes(ctx.captured_queries) == []
    assert body["accounts"] == [] and body["connected"] is False


def test_status_after_a_sync_still_never_writes(api, linked, providers) -> None:
    assert api.post("/api/v1/connections/pfm/sync").status_code == 200
    asked = len(providers.requests("pfm"))
    with CaptureQueriesContext(connection) as ctx:
        body = api.get("/api/v1/connections/pfm/status").json()
    assert writes(ctx.captured_queries) == []
    assert len(providers.requests("pfm")) == asked
    assert body["connected"] and body["accounts"][0]["handle"] == "Ateh"


def test_status_shows_an_unreadable_account_as_error_without_saving_it(
    api, env, user, settings
) -> None:
    env(META_ENV)
    row = lost_row(settings, user)
    with CaptureQueriesContext(connection) as ctx:
        data = api.get("/api/v1/connections/meta/status").json()
    assert [a["status"] for a in data["accounts"]] == ["error"] and not data[
        "connected"
    ]
    assert writes(ctx.captured_queries) == []
    stored = ConnectedAccount.objects.defer("access_token", "refresh_token").get(
        pk=row.pk
    )
    assert stored.status != AccountStatus.ERROR  # nothing was written by the GET


def test_sync_stores_the_users_accounts_and_is_idempotent(
    api, linked, providers
) -> None:
    first = api.post("/api/v1/connections/pfm/sync")
    again = api.post("/api/v1/connections/pfm/sync")
    assert first.status_code == again.status_code == 200
    assert first.json()["accounts"] == again.json()["accounts"]
    assert ConnectedAccount.objects.filter(provider="pfm").count() == 1
    assert providers.requests("pfm")[0].url.params["external_id"] == "lumi-link-1"


def test_sync_without_a_link_asks_pfm_nothing(api, env, providers) -> None:
    env(PFM_ENV)
    providers.on("pfm", PFM_ACCOUNTS)
    body = api.post("/api/v1/connections/pfm/sync").json()
    assert providers.requests("pfm") == []
    assert body["accounts"] == [] and body["connected"] is False


def test_sync_never_attaches_an_account_that_pfm_files_under_someone_else(
    api, linked, providers, other_user
) -> None:
    ConnectedAccount.objects.create(
        user=other_user,
        provider="pfm",
        external_account_id="sa_1",
        platform="x",
        display_name="theirs",
        handle="theirs-h",
    )
    body = api.post("/api/v1/connections/pfm/sync").json()
    assert body["accounts"] == []
    theirs = ConnectedAccount.objects.get(external_account_id="sa_1")
    assert theirs.user_id == other_user.pk
    assert (theirs.display_name, theirs.handle) == ("theirs", "theirs-h")
    assert theirs.status == AccountStatus.ACTIVE


def test_sync_needs_a_login_and_pfm_keys(api, env, providers) -> None:
    from rest_framework.test import APIClient

    assert APIClient().post("/api/v1/connections/pfm/sync").status_code == 401
    body = api.post("/api/v1/connections/pfm/sync").json()  # no PFM_JWT_TOKEN
    assert body["configured"] is False and providers.requests("pfm") == []


def test_sync_is_throttled_per_user(api, linked, other_user, settings) -> None:
    from django.core.cache import cache

    cache.clear()
    codes = [api.post("/api/v1/connections/pfm/sync").status_code for _ in range(14)]
    assert codes[:12] == [200] * 12 and codes[12:] == [429, 429]
    assert (
        client_for(other_user).post("/api/v1/connections/pfm/sync").status_code == 200
    )
