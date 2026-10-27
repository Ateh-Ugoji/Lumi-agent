"""``/api/v1/handles`` over the real Postgres. Xpoz is a mock transport, so no credit is spent."""

from __future__ import annotations

import httpx
import pytest
from django.db import IntegrityError, connection

from apps.connections import handles_api
from apps.connections.clients.xpoz import XpozClient
from apps.connections.handles.live import XpozHandleLive
from apps.connections.models import HandleSearchCache, XpozCreditLedger
from apps.connections.stores import DjangoCreditLedger
from apps.connections.tests.fakes import Recorder, fixture
from apps.profiles.models import HandleOrigin, SocialHandle, SocialProfile

from .test_api import client_for

pytestmark = pytest.mark.django_db

SEARCH = "/api/v1/handles/search"
SAVED = "/api/v1/handles/saved"
SELECT = "/api/v1/handles/select"
STATS = "/api/v1/handles/stats"


@pytest.fixture(autouse=True)
def wiring(settings, monkeypatch):
    settings.ROOT_URLCONF = "apps.connections.tests.db.urls"
    for name in (
        "XPOZ_API_KEY",
        "XPOZ_API_KEY_2",
        "XPOZ_LIVE_ENABLED",
        "XPOZ_RUN_CREDIT_BUDGET",
        "HANDLE_CACHE_TTL_MINUTES",
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def api(user):
    return client_for(user)


@pytest.fixture
def xpoz(monkeypatch):
    """Switch live lookups on and route them to a fixture. Returns the request recorder."""
    monkeypatch.setenv("XPOZ_API_KEY", "k-FAKE")
    monkeypatch.setenv("XPOZ_LIVE_ENABLED", "true")
    rec = Recorder(lambda r: httpx.Response(200, json=fixture("xpoz_users_x.json")))

    def make(user_id: int) -> XpozHandleLive:
        config = handles_api.get_config()
        return XpozHandleLive(
            XpozClient(
                config,
                transport=rec.transport,
                ledger=DjangoCreditLedger(user_id),
                run_id="test",
            )
        )

    monkeypatch.setattr(handles_api, "make_live", make)
    return rec


def test_every_route_needs_a_token(client) -> None:
    for method, url in (
        ("get", SEARCH),
        ("get", SAVED),
        ("post", SELECT),
        ("get", STATS),
    ):
        response = getattr(client, method)(url)
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "unauthenticated"


def test_a_short_query_answers_without_touching_anything(api, xpoz) -> None:
    body = api.get(SEARCH, {"q": "n"}).json()
    assert body["results"] == [] and body["reason"] == "min_length"
    assert xpoz.requests == []


def test_search_is_free_and_explains_why_when_live_is_off(api) -> None:
    response = api.get(SEARCH, {"q": "naval"})
    assert response.status_code == 200
    body = response.json()
    assert body["live"] is False and body["reason"] == "live_disabled"
    assert body["platform_reasons"] == {"x": "live_disabled"}
    assert XpozCreditLedger.objects.count() == 0


def test_a_live_search_returns_rows_and_records_the_spend(api, user, xpoz) -> None:
    body = api.get(SEARCH, {"q": "@Naval"}).json()
    assert body["live"] is True and body["reason"] is None
    names = [r["handle"] for r in body["results"]]
    assert names[0] == "naval"
    first = body["results"][0]
    assert set(first) == {
        "handle",
        "display_name",
        "avatar_url",
        "followers",
        "source",
        "platform",
    }
    assert first["source"] == "live" and first["platform"] == "x"
    assert len(xpoz.requests) == 1
    (entry,) = XpozCreditLedger.objects.all()
    assert entry.user_id == user.id and entry.credits == 2
    assert SocialHandle.objects.filter(platform="x", handle_normalized="naval").exists()


def test_the_second_search_comes_from_the_cache_and_costs_nothing(api, xpoz) -> None:
    api.get(SEARCH, {"q": "naval"})
    again = api.get(SEARCH, {"q": "naval"}).json()
    assert again["live"] is False
    assert {r["source"] for r in again["results"]} <= {"cache", "db"}
    assert len(xpoz.requests) == 1
    assert XpozCreditLedger.objects.count() == 1


def test_a_narrower_query_reuses_the_cached_answer(api, xpoz) -> None:
    api.get(SEARCH, {"q": "nav"})
    api.get(SEARCH, {"q": "naval"})
    assert len(xpoz.requests) == 1
    assert HandleSearchCache.objects.filter(platform="x").count() >= 1


def test_instagram_is_refused_when_its_own_budget_is_closed_and_nothing_is_sent(
    api, xpoz, monkeypatch
) -> None:
    monkeypatch.setenv("XPOZ_RUN_CREDIT_BUDGET_INSTAGRAM", "0")
    body = api.get(SEARCH, {"q": "ateh", "platforms": "instagram"}).json()
    assert body["reason"] == "budget_exhausted"
    assert xpoz.requests == [] and XpozCreditLedger.objects.count() == 0


def test_unknown_platforms_fall_back_to_x_and_linkedin_never_spends(api, xpoz) -> None:
    body = api.get(SEARCH, {"q": "naval", "platforms": "myspace"}).json()
    assert body["platforms"] == ["x"]
    xpoz.requests.clear()
    body = api.get(SEARCH, {"q": "naval", "platforms": "linkedin"}).json()
    assert body["platform_reasons"] == {"linkedin": "unsupported"}
    assert xpoz.requests == []


def test_an_xpoz_outage_is_reported_as_a_reason_and_not_cached(
    api, monkeypatch, xpoz
) -> None:
    broken = Recorder(lambda r: httpx.Response(503))
    monkeypatch.setattr(
        handles_api,
        "make_live",
        lambda uid: XpozHandleLive(
            XpozClient(handles_api.get_config(), transport=broken.transport)
        ),
    )
    response = api.get(SEARCH, {"q": "naval"})
    assert response.status_code == 200
    assert response.json()["reason"] == "provider_unavailable"
    assert HandleSearchCache.objects.count() == 0


def test_query_limits_are_validated(api) -> None:
    response = api.get(SEARCH, {"q": "x" * 101})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "validation_error"


def test_profile_handles_lead_only_for_their_owner(
    api, user, other_user, profile
) -> None:
    theirs = SocialHandle.objects.create(platform="x", handle_normalized="navalrival")
    SocialProfile.objects.create(user=other_user, handle=theirs)
    mine = SocialHandle.objects.create(platform="x", handle_normalized="navalmine")
    SocialProfile.objects.create(user=user, handle=mine)
    rows = api.get(SEARCH, {"q": "naval"}).json()["results"]
    by_handle = {r["handle"]: r["source"] for r in rows}
    assert by_handle["navalmine"] == "db"
    assert by_handle.get("navalrival") != "db"
    saved = {r["handle"]: r["source"] for r in api.get(SAVED).json()["results"]}
    assert saved["navalmine"] == "db" and saved.get("navalrival") != "db"


def test_select_remembers_the_handle_and_saved_returns_it(api) -> None:
    response = api.post(
        SELECT,
        {
            "handle": "@Karpathy",
            "display_name": "Andrej",
            "avatar_url": "https://img.example/a.png",
            "followers": 1200,
        },
        format="json",
    )
    assert response.status_code == 200
    assert response.json() == {
        "remembered": True,
        "handle": "karpathy",
        "platform": "x",
    }
    row = SocialHandle.objects.get(platform="x", handle_normalized="karpathy")
    assert row.origin == HandleOrigin.SELECTED and row.follower_count == 1200
    (saved,) = api.get(SAVED).json()["results"]
    assert saved["handle"].lower() == "karpathy"
    assert saved["followers"] == 1200 and saved["source"] == "cache"


def test_selecting_twice_keeps_one_row(api) -> None:
    for _ in range(2):
        api.post(SELECT, {"handle": "karpathy"}, format="json")
    assert SocialHandle.objects.filter(handle_normalized="karpathy").count() == 1


def test_select_rejects_bad_handles_and_platforms(api) -> None:
    for body in (
        {"handle": "has space"},
        {"handle": "!!"},
        {"handle": "ok", "platform": "myspace"},
        {"handle": "ok", "followers": -1},
        {"handle": "ok", "avatar_url": "javascript:alert(1)"},
        {},
    ):
        response = api.post(SELECT, body, format="json")
        assert response.status_code == 400, body
        assert response.json()["error"]["code"] == "validation_error"
    assert SocialHandle.objects.count() == 0


def test_saved_filters_by_platform_and_orders_by_followers(api) -> None:
    for handle, platform, followers in (
        ("small", "x", 10),
        ("big", "x", 5000),
        ("unknown", "x", None),
        ("igone", "instagram", 99),
    ):
        api.post(
            SELECT,
            {"handle": handle, "platform": platform, "followers": followers},
            format="json",
        )
    x_only = api.get(SAVED, {"platforms": "x"}).json()
    assert [r["handle"].lower() for r in x_only["results"]] == [
        "big",
        "small",
        "unknown",
    ]
    both = api.get(SAVED, {"platforms": "x,instagram"}).json()
    assert both["count"] == 4


def test_stats_counts_only_the_callers_credits(api, user, other_user, xpoz) -> None:
    XpozCreditLedger.objects.create(
        user=other_user, route="users", credits=12, key_slot=1
    )
    api.get(SEARCH, {"q": "naval"})
    body = api.get(STATS).json()
    assert body["credits_spent_24h"] == 2
    assert body["live_enabled"] is True and body["live_budget"] == 12
    assert body["live_budget_by_platform"] == {
        "x": 12,
        "instagram": 12,
        "tiktok": 12,
    }
    assert body["cached_searches"] == 1 and body["remembered_handles"] >= 3
    platforms = {p["id"]: p for p in body["available_platforms"]}
    assert platforms["instagram"] == {
        "id": "instagram",
        "label": "Instagram",
        "live": True,
        "credits": 12,
    }
    assert (
        platforms["linkedin"]["live"] is False and platforms["linkedin"]["credits"] == 0
    )


def test_stats_says_live_is_off_without_a_key(api, monkeypatch) -> None:
    monkeypatch.setenv("XPOZ_LIVE_ENABLED", "true")
    assert api.get(STATS).json()["live_enabled"] is False


def test_the_database_refuses_an_uppercase_handle(db) -> None:
    with pytest.raises(IntegrityError), connection.cursor() as cur:
        cur.execute(
            "INSERT INTO social_handles (platform, handle_normalized, handle_display,"
            " display_name, avatar_url, external_id, origin, last_seen_at, created_at,"
            " updated_at) VALUES ('x','UPPER','','','','','live',now(),now(),now())"
        )
