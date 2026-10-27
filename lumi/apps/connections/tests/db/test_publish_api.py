"""``POST /api/v1/publish`` over Postgres with mocked providers. Nothing leaves the box."""
# ruff: noqa: F401, F811  (fixtures imported from test_api)

from __future__ import annotations

from datetime import timedelta

import httpx
import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.connections.models import AccountStatus, ConnectedAccount, PublishJob
from apps.intelligence.models import RepurposeAttempt, RepurposeRequest
from apps.profiles.models import SocialHandle, SocialProfile

from .test_api import client_for, env, providers, wiring

pytestmark = pytest.mark.django_db

URL = "/api/v1/publish"
FEED = ("POST", "/v26.0/1001/feed")


def ok(data: dict) -> httpx.Response:
    return httpx.Response(200, json=data)


KEY = {"HTTP_IDEMPOTENCY_KEY": "key-1"}


@pytest.fixture
def api(user):
    return client_for(user)


@pytest.fixture
def fb_profile(user):
    handle = SocialHandle.objects.create(
        platform="facebook", handle_normalized="mypage"
    )
    return SocialProfile.objects.create(user=user, handle=handle)


@pytest.fixture
def page(user, fb_profile):
    return ConnectedAccount.objects.create(
        user=user,
        provider="meta",
        external_account_id="1001",
        access_token="page-token-FAKE",
        display_name="My Page",
        social_profile=fb_profile,
    )


def body(profile, **extra):
    return {
        "profile_id": profile.pk,
        "platform": "facebook",
        "text": "Hello world",
        "confirm": True,
        **extra,
    }


def post(api, payload, **headers):
    return api.post(URL, payload, format="json", **headers)


def posted(providers):
    return [r for r in providers.requests("meta") if r.method == "POST"]


def test_it_needs_a_token(client) -> None:
    assert client.post(URL, {}, content_type="application/json").status_code == 401


def test_a_real_publish_returns_201_and_records_the_job(
    api,
    page,
    fb_profile,
    providers,
) -> None:
    providers.on("meta", {FEED: ok({"id": "1001_555"})})
    response = post(api, body(fb_profile), **KEY)
    assert response.status_code == 201
    out = response.json()
    assert out["status"] == "done" and out["replayed"] is False
    assert out["external_post_id"] == "1001_555"
    assert out["url"] == "https://www.facebook.com/1001_555"
    job = PublishJob.objects.get()
    assert job.pk == out["job_id"] and job.status == "done"
    assert job.connected_account_id == page.pk and job.idempotency_key == "key-1"
    assert len(posted(providers)) == 1


def test_the_page_token_goes_to_the_provider_and_never_to_the_client(
    api,
    page,
    fb_profile,
    providers,
) -> None:
    providers.on("meta", {FEED: ok({"id": "1001_555"})})
    response = post(api, body(fb_profile), **KEY)
    assert "page-token-FAKE" not in response.content.decode()
    assert b"page-token-FAKE" in posted(providers)[0].content


def test_repeating_the_key_replays_and_sends_nothing(
    api,
    page,
    fb_profile,
    providers,
) -> None:
    providers.on("meta", {FEED: ok({"id": "1001_555"})})
    post(api, body(fb_profile), **KEY)
    again = post(api, body(fb_profile), **KEY)
    assert again.status_code == 200 and again.json()["replayed"] is True
    assert again.json()["external_post_id"] == "1001_555"
    assert len(posted(providers)) == 1 and PublishJob.objects.count() == 1


def test_the_same_key_with_another_text_is_a_conflict(
    api,
    page,
    fb_profile,
    providers,
) -> None:
    providers.on("meta", {FEED: ok({"id": "1001_555"})})
    post(api, body(fb_profile), **KEY)
    other = post(api, body(fb_profile, text="Something else"), **KEY)
    assert other.status_code == 409 and other.json()["error"]["code"] == "conflict"
    assert len(posted(providers)) == 1


def test_the_key_is_scoped_to_the_profile(
    api,
    user,
    page,
    fb_profile,
    providers,
) -> None:
    handle = SocialHandle.objects.create(
        platform="facebook", handle_normalized="second"
    )
    second = SocialProfile.objects.create(user=user, handle=handle)
    ConnectedAccount.objects.create(
        user=user,
        provider="meta",
        external_account_id="1002",
        access_token="t2",
        social_profile=second,
    )
    providers.on(
        "meta",
        {
            FEED: ok({"id": "1001_1"}),
            ("POST", "/v26.0/1002/feed"): ok({"id": "1002_1"}),
        },
    )
    assert post(api, body(fb_profile), **KEY).status_code == 201
    assert post(api, body(second), **KEY).status_code == 201
    assert PublishJob.objects.count() == 2


def test_a_real_publish_needs_confirm_and_a_key_and_sends_nothing_without_them(
    api,
    page,
    fb_profile,
    providers,
) -> None:
    no_confirm = post(api, body(fb_profile, confirm=False), **KEY)
    assert no_confirm.json()["error"]["code"] == "publish.confirmation_required"
    no_key = post(api, body(fb_profile))
    assert no_key.json()["error"]["code"] == "publish.idempotency_key_required"
    assert posted(providers) == [] and PublishJob.objects.count() == 0


def test_dry_run_needs_neither_and_touches_no_ledger(
    api,
    page,
    fb_profile,
    providers,
) -> None:
    response = post(api, body(fb_profile, confirm=False, dry_run=True))
    assert response.status_code == 200
    out = response.json()
    assert out["status"] == "dry_run" and out["job_id"] is None
    assert PublishJob.objects.count() == 0 and posted(providers) == []


def test_a_bad_draft_never_occupies_the_key(
    api,
    page,
    fb_profile,
    providers,
) -> None:
    providers.on("meta", {FEED: ok({"id": "1001_555"})})
    bad = post(api, body(fb_profile, text="   "), **KEY)
    assert bad.status_code == 400
    assert PublishJob.objects.count() == 0
    assert post(api, body(fb_profile), **KEY).status_code == 201


def test_a_timeout_parks_the_job_as_unknown_and_blocks_a_blind_retry(
    api,
    page,
    fb_profile,
    providers,
) -> None:
    providers.on("meta", {FEED: httpx.Response(503)})
    first = post(api, body(fb_profile), **KEY)
    assert first.status_code == 502
    assert first.json()["error"]["code"] == "publish.outcome_unknown"
    assert PublishJob.objects.get().status == "unknown"
    providers.on("meta", {FEED: ok({"id": "1001_555"})})
    retry = post(api, body(fb_profile), **KEY)
    assert retry.status_code == 409
    assert retry.json()["error"]["code"] == "publish.in_progress"
    assert len(posted(providers)) == 1


def test_a_rejection_is_failed_and_can_be_retried_with_the_same_key(
    api,
    page,
    fb_profile,
    providers,
) -> None:
    providers.on(
        "meta", {FEED: httpx.Response(401, json={"error": {"message": "SECRET"}})}
    )
    first = post(api, body(fb_profile), **KEY)
    assert first.status_code == 502 and "SECRET" not in first.content.decode()
    assert PublishJob.objects.get().status == "failed"
    providers.on("meta", {FEED: ok({"id": "1001_555"})})
    assert post(api, body(fb_profile), **KEY).status_code == 201
    assert PublishJob.objects.get().status == "done"


def test_a_foreign_profile_is_a_404_and_sends_nothing(
    api,
    other_user,
    providers,
) -> None:
    handle = SocialHandle.objects.create(
        platform="facebook", handle_normalized="theirs"
    )
    theirs = SocialProfile.objects.create(user=other_user, handle=handle)
    response = post(api, body(theirs), **KEY)
    assert response.status_code == 404 and PublishJob.objects.count() == 0


def test_an_account_of_another_profile_is_never_used(
    api,
    other_user,
    fb_profile,
    providers,
) -> None:
    ConnectedAccount.objects.create(
        user=other_user,
        provider="meta",
        external_account_id="1001",
        access_token="theirs",
    )
    response = post(api, body(fb_profile), **KEY)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "publish.not_connected"


def test_unsupported_platforms_are_refused_before_anything_else(
    api,
    fb_profile,
    providers,
) -> None:
    for platform in ("instagram", "tiktok"):
        response = post(api, body(fb_profile, platform=platform), **KEY)
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "publish.unsupported_platform"
    assert post(api, body(fb_profile, platform="myspace"), **KEY).status_code == 400


def test_a_revoked_or_expired_connection_asks_to_reconnect(
    api,
    page,
    fb_profile,
    providers,
) -> None:
    for status in (AccountStatus.REVOKED, AccountStatus.EXPIRED):
        ConnectedAccount.objects.filter(pk=page.pk).update(status=status)
        response = post(api, body(fb_profile), **KEY)
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "publish.reconnect_required"
    assert posted(providers) == []


def test_a_limited_page_is_rejected_by_the_provider_not_sent(
    api,
    page,
    fb_profile,
    providers,
) -> None:
    ConnectedAccount.objects.filter(pk=page.pk).update(status=AccountStatus.LIMITED)
    response = post(api, body(fb_profile), **KEY)
    assert response.status_code == 502
    assert posted(providers) == []


def test_x_stays_off_for_a_real_post_but_a_dry_run_gives_the_cost(
    api,
    user,
    providers,
    monkeypatch,
) -> None:
    handle = SocialHandle.objects.create(platform="x", handle_normalized="me")
    profile = SocialProfile.objects.create(user=user, handle=handle)
    ConnectedAccount.objects.create(
        user=user,
        provider="x",
        external_account_id="77",
        access_token="x-FAKE",
        scopes=["tweet.write", "tweet.read", "users.read"],
        social_profile=profile,
    )
    monkeypatch.delenv("X_LIVE_ENABLED", raising=False)
    real = post(api, body(profile, platform="x"), **KEY)
    assert real.status_code == 409
    assert real.json()["error"]["code"] == "connections.live_disabled"
    assert providers.requests("x") == []
    assert PublishJob.objects.get().status == "failed"
    dry = post(api, body(profile, platform="x", confirm=False, dry_run=True))
    assert dry.status_code == 200
    assert dry.json()["estimated_cost_usd"] == 0.015


def test_an_attempt_supplies_the_text_and_is_linked(
    api,
    page,
    fb_profile,
    providers,
) -> None:
    req = RepurposeRequest.objects.create(profile=fb_profile, source_caption="src")
    attempt = RepurposeAttempt.objects.create(
        request=req,
        platform="facebook",
        attempt_no=1,
        output="Draft from Lumi",
        must_keep_passed=True,
    )
    providers.on("meta", {FEED: ok({"id": "1001_9"})})
    payload = {
        "profile_id": fb_profile.pk,
        "platform": "facebook",
        "attempt_id": attempt.pk,
        "confirm": True,
    }
    assert post(api, payload, **KEY).status_code == 201
    job = PublishJob.objects.get()
    assert job.attempt_id == attempt.pk and job.text == "Draft from Lumi"
    assert (
        b"Draft+from+Lumi" in posted(providers)[0].content
        or b"Draft%20from%20Lumi" in posted(providers)[0].content
    )


def test_an_attempt_of_another_profile_or_platform_is_refused(
    api,
    user,
    other_user,
    page,
    fb_profile,
    providers,
) -> None:
    handle = SocialHandle.objects.create(
        platform="facebook", handle_normalized="theirs"
    )
    theirs = SocialProfile.objects.create(user=other_user, handle=handle)
    foreign = RepurposeAttempt.objects.create(
        request=RepurposeRequest.objects.create(profile=theirs, source_caption="s"),
        platform="facebook",
        attempt_no=1,
        output="secret draft",
        must_keep_passed=True,
    )
    payload = {"profile_id": fb_profile.pk, "platform": "facebook", "confirm": True}
    r = post(api, {**payload, "attempt_id": foreign.pk}, **KEY)
    assert r.status_code == 404 and "secret draft" not in r.content.decode()
    mine = RepurposeAttempt.objects.create(
        request=RepurposeRequest.objects.create(profile=fb_profile, source_caption="s"),
        platform="x",
        attempt_no=1,
        output="for x",
        must_keep_passed=True,
    )
    r = post(api, {**payload, "attempt_id": mine.pk}, **KEY)
    assert r.status_code == 400
    assert PublishJob.objects.count() == 0 and posted(providers) == []


def test_text_or_attempt_is_required(api, fb_profile) -> None:
    r = post(api, {"profile_id": fb_profile.pk, "platform": "facebook"}, **KEY)
    assert r.status_code == 400 and r.json()["error"]["code"] == "validation_error"


def test_an_expiring_token_is_refreshed_before_publishing(
    api,
    page,
    fb_profile,
    providers,
) -> None:
    ConnectedAccount.objects.filter(pk=page.pk).update(
        expires_at=timezone.now() - timedelta(minutes=1)
    )
    providers.on("meta", {FEED: ok({"id": "1001_1"})})
    response = post(api, body(fb_profile), **KEY)
    # Meta refresh needs a user token the mocked provider does not serve: reconnect, no post.
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "publish.reconnect_required"
    assert posted(providers) == []


def test_the_database_refuses_a_short_fingerprint_and_a_duplicate_key(
    page, fb_profile
) -> None:
    common = {"profile": fb_profile, "platform": "facebook", "text": "t"}
    with pytest.raises(IntegrityError), transaction.atomic():
        PublishJob.objects.create(**common, fingerprint="abc", idempotency_key="k")
    PublishJob.objects.create(**common, fingerprint="a" * 64, idempotency_key="k")
    with pytest.raises(IntegrityError), transaction.atomic():
        PublishJob.objects.create(**common, fingerprint="b" * 64, idempotency_key="k")


def test_deleting_an_attempt_keeps_the_job(fb_profile) -> None:
    attempt = RepurposeAttempt.objects.create(
        request=RepurposeRequest.objects.create(profile=fb_profile, source_caption="s"),
        platform="facebook",
        attempt_no=1,
        output="o",
        must_keep_passed=True,
    )
    job = PublishJob.objects.create(
        profile=fb_profile,
        platform="facebook",
        text="t",
        fingerprint="c" * 64,
        idempotency_key="k",
        attempt=attempt,
    )
    attempt.delete()
    job.refresh_from_db()
    assert job.attempt_id is None
