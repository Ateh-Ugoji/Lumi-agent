"""``/api/v1/profiles/*`` and ``/api/v1/jobs/*`` end to end against Postgres."""

from datetime import UTC, datetime

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.core.models import BackgroundJob
from apps.profiles import services
from apps.profiles.models import SocialProfile
from lumi_ai.ports import PostIn, PostMetrics

pytestmark = pytest.mark.django_db
BASE = "/api/v1"


def post_in(external_id, **kw):
    base = {
        "platform": "x",
        "external_id": external_id,
        "text": "cap",
        "kind": "original",
        "published_at": datetime(2026, 10, 1, tzinfo=UTC),
    }
    return PostIn(**{**base, **kw})


def url(profile, tail=""):
    return f"{BASE}/profiles/{profile.pk}{tail}"


def test_every_route_requires_a_token(client, profile):
    for method, path in [
        ("get", f"{BASE}/profiles"),
        ("post", f"{BASE}/profiles"),
        ("post", url(profile, "/select")),
        ("get", url(profile, "/analytics")),
        ("post", url(profile, "/refresh")),
        ("get", url(profile, "/alerts/unread")),
        ("post", url(profile, "/alerts/1/dismiss")),
        ("get", url(profile, "/listening")),
        ("put", url(profile, "/listening")),
        ("get", f"{BASE}/jobs/{BackgroundJob().pk}"),
    ]:
        response = getattr(client, method)(path)
        assert response.status_code == 401, (method, path)
        assert response.json()["error"]["code"]


@pytest.mark.parametrize(
    ("method", "tail"),
    [
        ("post", "/select"),
        ("get", "/analytics"),
        ("post", "/refresh"),
        ("get", "/alerts/unread"),
        ("post", "/alerts/1/dismiss"),
        ("get", "/listening"),
        ("put", "/listening"),
    ],
)
def test_a_foreign_profile_is_a_404(stranger_api, profile, method, tail):
    body = {"keywords": [], "enabled": False} if method == "put" else None
    response = getattr(stranger_api, method)(url(profile, tail), body, format="json")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_list_only_returns_my_profiles(api, profile, stranger, make_profile):
    make_profile(stranger, "theirs")
    body = api.get(f"{BASE}/profiles").json()
    assert [p["handle"] for p in body["profiles"]] == ["ateh"]
    assert set(body["profiles"][0]) == {
        "id",
        "name",
        "platform",
        "handle",
        "has_voice_profile",
        "listening_active",
        "timezone",
        "timezone_source",
    }


def test_list_query_count_does_not_grow(api, owner, make_profile):
    make_profile(owner, "first")
    api.get(f"{BASE}/profiles")  # the first request of a token also stamps last_used_at
    with CaptureQueriesContext(connection) as small:
        api.get(f"{BASE}/profiles")
    for i in range(8):
        make_profile(owner, f"more{i}")
    with CaptureQueriesContext(connection) as big:
        assert len(api.get(f"{BASE}/profiles").json()["profiles"]) == 9
    assert len(big) == len(small)


def test_create_profile_makes_handle_profile_and_a_bootstrap_job(api, owner):
    response = api.post(
        f"{BASE}/profiles", {"platform": "x", "handle": "@NewOne"}, format="json"
    )
    assert response.status_code == 201
    body = response.json()
    assert (body["handle"], body["platform"]) == ("NewOne", "x")
    job = BackgroundJob.objects.get(pk=body["job_id"])
    assert (job.kind, job.status, job.profile_id, job.user_id) == (
        "profile.bootstrap",
        "queued",
        body["id"],
        owner.pk,
    )


def test_creating_the_same_profile_again_is_200_without_a_second_job(api):
    first = api.post(
        f"{BASE}/profiles", {"platform": "x", "handle": "same"}, format="json"
    )
    again = api.post(
        f"{BASE}/profiles", {"platform": "x", "handle": "@Same"}, format="json"
    )
    assert (first.status_code, again.status_code) == (201, 200)
    assert again.json()["id"] == first.json()["id"]
    assert again.json()["job_id"] is None
    assert BackgroundJob.objects.count() == 1


@pytest.mark.parametrize(
    "body",
    [
        {"platform": "x", "handle": "has space"},
        {"platform": "x", "handle": "a" * 16},
        {"platform": "myspace", "handle": "ok"},
        {"platform": "x"},
        {},
    ],
)
def test_create_profile_rejects_bad_input(api, body):
    response = api.post(f"{BASE}/profiles", body, format="json")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "validation_error"
    assert SocialProfile.objects.count() == 0


def test_select_returns_the_summary(api, profile):
    body = api.post(url(profile, "/select")).json()
    assert body == {
        "profile_id": profile.pk,
        "name": "ateh",
        "voice_profile_exists": False,
        "post_count": 0,
        "listening_active": False,
    }


def test_analytics_is_read_only_and_empty_without_posts(api, profile):
    before = BackgroundJob.objects.count()
    body = api.get(url(profile, "/analytics")).json()
    assert body["is_live_data"] is False
    assert BackgroundJob.objects.count() == before


def test_analytics_with_data(api, profile):
    services.upsert_posts(
        profile.handle_id,
        [
            PostIn(
                platform="x",
                external_id="1",
                text="hello",
                kind="original",
                published_at=datetime(2026, 10, 1, tzinfo=UTC),
                metrics=PostMetrics(views=50, likes=5),
            )
        ],
    )
    body = api.get(url(profile, "/analytics")).json()
    assert (body["is_live_data"], body["total_impressions"]) == (True, 50)


def test_refresh_returns_202_with_a_job_and_dedupes_while_active(api, profile):
    first = api.post(url(profile, "/refresh"))
    second = api.post(url(profile, "/refresh"))
    assert first.status_code == second.status_code == 202
    assert first.json()["job_id"] == second.json()["job_id"]
    assert BackgroundJob.objects.get().kind == "profile.refresh"


def test_unread_alerts_shape_and_dismiss(api, profile):
    [post_id] = services.upsert_posts(
        profile.handle_id,
        [post_in("1")],
    ).post_ids
    services.create_alert_once(profile.pk, post_id, "spike", velocity=4.0)
    alerts = api.get(url(profile, "/alerts/unread")).json()["alerts"]
    assert len(alerts) == 1
    alert = alerts[0]
    assert alert["velocity"] == {"likes_per_hour": 4.0, "baseline_likes_per_hour": None}
    assert (alert["caption"], alert["platform_post_id"], alert["kind"]) == (
        "cap",
        "1",
        "spike",
    )
    assert set(alert) == {
        "id",
        "post_id",
        "caption",
        "platform_post_id",
        "alerted_at",
        "kind",
        "velocity",
    }
    assert api.post(url(profile, f"/alerts/{alert['id']}/dismiss")).status_code == 204
    assert api.get(url(profile, "/alerts/unread")).json() == {"alerts": []}
    assert api.post(url(profile, "/alerts/99999/dismiss")).status_code == 404


def test_unread_alerts_query_count_is_constant(api, profile):
    ids = services.upsert_posts(
        profile.handle_id,
        [post_in(str(i)) for i in range(15)],
    ).post_ids
    services.create_alert_once(profile.pk, ids[0], "spike")
    api.get(url(profile, "/alerts/unread"))  # stamps the token's last_used_at
    with CaptureQueriesContext(connection) as small:
        api.get(url(profile, "/alerts/unread"))
    for pid in ids[1:]:
        services.create_alert_once(profile.pk, pid, "spike")
    with CaptureQueriesContext(connection) as big:
        assert len(api.get(url(profile, "/alerts/unread")).json()["alerts"]) == 15
    assert len(big) == len(small)


def test_a_stranger_cannot_dismiss_through_my_alert_id(
    stranger_api, stranger, make_profile, profile
):
    [post_id] = services.upsert_posts(profile.handle_id, [post_in("1")]).post_ids
    services.create_alert_once(profile.pk, post_id, "spike")
    mine = make_profile(stranger, "mine")
    from apps.profiles.models import Alert

    alert_id = Alert.objects.get().pk
    assert (
        stranger_api.post(url(mine, f"/alerts/{alert_id}/dismiss")).status_code == 404
    )
    assert Alert.objects.get().status == "active"


def test_listening_defaults_then_put_replaces(api, profile):
    assert api.get(url(profile, "/listening")).json() == {
        "keywords": [],
        "enabled": False,
        "interval_minutes": None,
    }
    body = {
        "keywords": ["AI", "ai", "  cats "],
        "enabled": True,
        "interval_minutes": 15,
    }
    response = api.put(url(profile, "/listening"), body, format="json")
    assert response.status_code == 200
    assert response.json() == {
        "keywords": ["AI", "cats"],
        "enabled": True,
        "interval_minutes": 15,
    }
    assert api.get(url(profile, "/listening")).json() == response.json()


@pytest.mark.parametrize(
    "body",
    [
        {"keywords": ["x"], "enabled": True, "interval_minutes": 0},
        {"keywords": ["x"], "enabled": True, "interval_minutes": 1441},
        {"keywords": ["x" * 101], "enabled": True},
        {"keywords": [str(i) for i in range(51)], "enabled": True},
        {"keywords": "oops", "enabled": True},
        {"enabled": True},
    ],
)
def test_listening_rejects_bad_bodies_and_changes_nothing(api, profile, body):
    api.put(
        url(profile, "/listening"),
        {"keywords": ["keep"], "enabled": True, "interval_minutes": 5},
        format="json",
    )
    response = api.put(url(profile, "/listening"), body, format="json")
    assert response.status_code == 400
    assert api.get(url(profile, "/listening")).json()["keywords"] == ["keep"]


def test_job_endpoint_shows_state_and_hides_other_users_jobs(
    api, stranger_api, profile
):
    job_id = api.post(url(profile, "/refresh")).json()["job_id"]
    body = api.get(f"{BASE}/jobs/{job_id}").json()
    assert set(body) == {
        "id",
        "kind",
        "status",
        "progress",
        "result",
        "error_code",
        "error_message",
        "created_at",
        "started_at",
        "finished_at",
    }
    assert (body["id"], body["status"], body["kind"]) == (
        job_id,
        "queued",
        "profile.refresh",
    )
    assert stranger_api.get(f"{BASE}/jobs/{job_id}").status_code == 404
    assert api.get(f"{BASE}/jobs/not-a-uuid").status_code == 404


def test_profile_refresh_is_queued_until_the_dispatcher_runs_it(api, profile, settings):
    """``profile.refresh`` has a handler (INTELLIGENCE) but ``LUMI_JOB_DISPATCH=none`` never runs it.

    The refresh job waits in ``queued``; the client polls ``GET /jobs/{id}`` and sees that state.
    """
    from apps.core import jobs

    settings.LUMI_JOB_DISPATCH = "none"
    assert {"profile.bootstrap", "profile.refresh"} <= set(jobs.registered_kinds())

    job_id = api.post(url(profile, "/refresh")).json()["job_id"]
    body = api.get(f"{BASE}/jobs/{job_id}").json()
    assert (body["kind"], body["status"]) == ("profile.refresh", "queued")
    assert not body["result"] and not body["error_code"]


def test_profile_refresh_fails_cleanly_when_the_posts_cannot_be_read(
    api, profile, settings
):
    """No connected account: the job ends ``failed`` with a fixed code, not a provider message."""
    from apps.core import jobs

    job_id = api.post(url(profile, "/refresh")).json()["job_id"]
    assert jobs.run_job(job_id) == "failed"
    body = api.get(f"{BASE}/jobs/{job_id}").json()
    assert (body["status"], body["error_code"]) == ("failed", "profiles.sync_failed")
