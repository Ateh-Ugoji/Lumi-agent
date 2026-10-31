"""``/api/v1/trends/*``."""

from datetime import UTC, datetime, timedelta

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.core import agent_runtime
from apps.profiles import services
from apps.profiles.models import MetricSnapshot
from lumi_ai.ports import PostIn, PostMetrics

pytestmark = pytest.mark.django_db
BASE = "/api/v1/trends"
T0 = datetime(2026, 10, 1, tzinfo=UTC)


def peer_post(profile, handle, external_id, likes=10, avatar_url="", **kw):
    """Store a post of another account and link it as a listening match."""
    hid = services.get_or_create_handle(
        "x", handle, origin="niche", avatar_url=avatar_url
    )
    [post_id] = services.upsert_posts(
        hid,
        [
            PostIn(
                platform="x",
                external_id=external_id,
                text=f"caption {external_id}",
                kind="original",
                published_at=T0,
                url=f"https://x.com/{handle}/status/{external_id}",
                metrics=PostMetrics(likes=likes, views=likes * 10),
            )
        ],
    ).post_ids
    services.record_listening_match(profile.pk, post_id, keyword=kw.pop("keyword", None))
    return post_id


class FakeRuntime:
    def __init__(self, result):
        self.result, self.calls = result, []

    async def scan_trends(self, profile_id, handles, min_likes, keywords=None):
        self.calls.append((profile_id, handles, min_likes, keywords))
        return self.result


@pytest.fixture
def fake_scan():
    def install(result):
        fake = FakeRuntime(result)
        agent_runtime.set_runtime(fake)
        return fake

    yield install
    agent_runtime.set_runtime(None)


def test_routes_need_a_token(client, profile):
    assert client.get(f"{BASE}/matches?profile_id={profile.pk}").status_code == 401
    assert client.post(f"{BASE}/scan").status_code == 401


def test_matches_of_a_foreign_profile_are_a_404(stranger_api, profile):
    assert (
        stranger_api.get(f"{BASE}/matches?profile_id={profile.pk}").status_code == 404
    )


@pytest.mark.parametrize("query", ["", "&limit=0", "&limit=201", "&limit=x"])
def test_matches_validate_the_query(api, profile, query):
    url = f"{BASE}/matches" + (f"?profile_id={profile.pk}{query}" if query else "")
    assert api.get(url).status_code == 400


def test_matches_shape_and_latest_metrics(api, profile):
    post_id = peer_post(profile, "Sama", "1", likes=10)
    MetricSnapshot.objects.create(
        post_id=post_id,
        captured_at=datetime.now(UTC) + timedelta(days=2),
        likes=500,
        views=9000,
    )
    [match] = api.get(f"{BASE}/matches?profile_id={profile.pk}").json()["matches"]
    assert set(match) == {
        "id",
        "profile_id",
        "platform",
        "platform_post_id",
        "author_handle",
        "caption",
        "platform_url",
        "author_avatar_url",
        "metrics",
        "discovered_at",
        "keyword",
    }
    assert (match["platform"], match["author_handle"], match["platform_post_id"]) == (
        "x",
        "Sama",
        "1",
    )
    assert match["platform_url"] == "https://x.com/Sama/status/1"
    assert (match["metrics"]["likes"], match["metrics"]["views"]) == (500, 9000)
    assert match["profile_id"] == profile.pk


def test_matches_are_newest_first_limited_and_only_mine(
    api, profile, stranger, make_profile
):
    for i in range(5):
        peer_post(profile, "peer", str(i))
    peer_post(make_profile(stranger, "other"), "peer", "99")
    ids = [
        m["platform_post_id"]
        for m in api.get(f"{BASE}/matches?profile_id={profile.pk}").json()["matches"]
    ]
    assert ids == ["4", "3", "2", "1", "0"]
    limited = api.get(f"{BASE}/matches?profile_id={profile.pk}&limit=2").json()[
        "matches"
    ]
    assert [m["platform_post_id"] for m in limited] == ["4", "3"]


def test_matches_query_count_is_constant(api, profile):
    peer_post(profile, "peer", "0")
    api.get(
        f"{BASE}/matches?profile_id={profile.pk}"
    )  # stamps the token's last_used_at
    with CaptureQueriesContext(connection) as small:
        api.get(f"{BASE}/matches?profile_id={profile.pk}")
    for i in range(1, 25):
        peer_post(profile, f"peer{i % 5}", str(i))
    with CaptureQueriesContext(connection) as big:
        assert (
            len(api.get(f"{BASE}/matches?profile_id={profile.pk}").json()["matches"])
            == 25
        )
    assert len(big) == len(small)


def test_a_match_without_snapshots_has_null_metrics(api, profile):
    post_id = peer_post(profile, "peer", "1")
    MetricSnapshot.objects.filter(post_id=post_id).delete()
    [match] = api.get(f"{BASE}/matches?profile_id={profile.pk}").json()["matches"]
    assert match["metrics"] is None


def test_scan_passes_the_request_to_the_agent_registry(api, profile, fake_scan):
    fake = fake_scan(
        {
            "new_matches_found": 1,
            "viral_posts": [{"author": "a", "likes": 90}],
            "scanned_handles": {"a": 5},
        }
    )
    response = api.post(
        f"{BASE}/scan",
        {"profile_id": profile.pk, "handles": ["a"], "min_likes": 50},
        format="json",
    )
    assert response.status_code == 200
    assert response.json() == {
        "profile_id": profile.pk,
        "new_matches_found": 1,
        "viral_posts": [{"author": "a", "likes": 90}],
    }
    assert fake.calls == [(profile.pk, ["a"], 50, None)]


def test_scan_defaults_leave_handles_to_the_profile_niche(api, profile, fake_scan):
    fake = fake_scan({"new_matches_found": 0, "viral_posts": []})
    assert (
        api.post(f"{BASE}/scan", {"profile_id": profile.pk}, format="json").status_code
        == 200
    )
    assert fake.calls == [(profile.pk, None, 20, None)]


def test_scan_passes_keywords_and_matches_filter_by_them(api, profile, fake_scan):
    fake = fake_scan({"new_matches_found": 2, "viral_posts": [], "keywords": ["a", "b"]})
    response = api.post(
        f"{BASE}/scan",
        {"profile_id": profile.pk, "keywords": ["lagos tech"], "min_likes": 10},
        format="json",
    )
    assert response.status_code == 200
    assert response.json()["keywords"] == ["a", "b"]
    assert fake.calls == [(profile.pk, None, 10, ["lagos tech"])]

    peer_post(profile, "peer", "7", keyword="Lagos Tech")
    peer_post(profile, "peer", "8")
    everything = api.get(f"{BASE}/matches?profile_id={profile.pk}").json()["matches"]
    assert len(everything) == 2
    filtered = api.get(
        f"{BASE}/matches?profile_id={profile.pk}&keyword=lagos%20tech"
    ).json()["matches"]
    assert [(m["platform_post_id"], m["keyword"]) for m in filtered] == [
        ("7", "Lagos Tech")
    ]


def test_scan_requires_my_profile_id(api, stranger_api, profile, fake_scan):
    fake = fake_scan({"new_matches_found": 0, "viral_posts": []})
    assert api.post(f"{BASE}/scan", {}, format="json").status_code == 400
    assert (
        stranger_api.post(
            f"{BASE}/scan", {"profile_id": profile.pk}, format="json"
        ).status_code
        == 404
    )
    assert fake.calls == []


@pytest.mark.parametrize(
    "body", [{"min_likes": -1}, {"handles": "sama"}, {"handles": ["a"] * 21}]
)
def test_scan_rejects_bad_bodies(api, profile, fake_scan, body):
    fake = fake_scan({})
    assert (
        api.post(
            f"{BASE}/scan", {"profile_id": profile.pk, **body}, format="json"
        ).status_code
        == 400
    )
    assert fake.calls == []


def test_a_failed_scan_is_a_502_with_the_reason(api, profile, fake_scan):
    fake_scan({"error": "no accounts to check on x", "new_matches_found": 0})
    response = api.post(f"{BASE}/scan", {"profile_id": profile.pk}, format="json")
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "profiles.scan_failed"
    assert response.json()["error"]["details"]["reason"] == "no accounts to check on x"


def avatars(api, profile):
    matches = api.get(f"{BASE}/matches?profile_id={profile.pk}").json()["matches"]
    return {m["author_handle"]: m["author_avatar_url"] for m in matches}


def test_matches_carry_the_picture_stored_for_the_author(api, profile):
    peer_post(profile, "Sama", "1", avatar_url="https://img.example/sama.png")
    assert avatars(api, profile) == {"Sama": "https://img.example/sama.png"}


def test_matches_say_null_when_nobody_knows_the_picture(api, profile):
    peer_post(profile, "Sama", "1")
    assert avatars(api, profile) == {"Sama": None}


def test_a_picture_gets_filled_in_once_a_later_scan_learns_it(api, profile):
    peer_post(profile, "Sama", "1")
    assert avatars(api, profile) == {"Sama": None}
    services.get_or_create_handle(
        "x", "sama", origin="niche", avatar_url="https://img.example/s.png"
    )
    assert avatars(api, profile) == {"Sama": "https://img.example/s.png"}


@pytest.mark.parametrize(
    "stored", ["javascript:alert(1)", "data:text/html;base64,AAAA", "//cdn/x.png"]
)
def test_matches_never_hand_out_a_picture_that_is_not_http(api, profile, stored):
    peer_post(profile, "Sama", "1", avatar_url=stored)
    assert avatars(api, profile) == {"Sama": None}


def test_the_picture_adds_no_queries(api, profile):
    peer_post(profile, "peer0", "0", avatar_url="https://img.example/0.png")
    api.get(f"{BASE}/matches?profile_id={profile.pk}")
    with CaptureQueriesContext(connection) as small:
        api.get(f"{BASE}/matches?profile_id={profile.pk}")
    for i in range(1, 15):
        peer_post(
            profile, f"peer{i}", str(i), avatar_url=f"https://img.example/{i}.png"
        )
    with CaptureQueriesContext(connection) as big:
        found = avatars(api, profile)
    assert len(found) == 15 and all(found.values())
    assert len(big) == len(small)


def test_the_openapi_schema_documents_the_picture(client, settings):
    settings.DEBUG = True
    schema = client.get("/api/schema/?format=json").json()
    item = schema["components"]["schemas"]["TrendMatch"]
    assert item["properties"]["author_avatar_url"]["nullable"] is True
    assert "author_avatar_url" in item["required"]
    path = schema["paths"]["/api/v1/trends/matches"]["get"]
    assert {p["name"] for p in path["parameters"]} >= {"profile_id", "limit"}
