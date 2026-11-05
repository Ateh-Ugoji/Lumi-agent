# ruff: noqa: F811
"""``OwnPostSync`` reading a connected Facebook Page through Meta, with a mocked Graph and no network."""

from __future__ import annotations

import httpx
import pytest
from asgiref.sync import async_to_sync

from apps.connections import own_post_sync
from apps.connections.models import ConnectedAccount, IngestPass
from apps.connections.own_post_sync import DjangoOwnPostSync
from apps.connections.tests.db.test_api import (  # noqa: F401  (fixtures)
    PFM_ENV,
    env,
    providers,
    wiring,
)
from apps.profiles.models import MetricSnapshot, Post, SocialHandle, SocialProfile
from lumi_ai.ports import ProviderAuthError, ProviderUnavailable

pytestmark = pytest.mark.django_db

PAGE = "1001"
GRAPH = "/v26.0"
TOKEN = "meta-page-FAKE"


@pytest.fixture
def fb(user) -> SocialProfile:
    handle = SocialHandle.objects.create(platform="facebook", handle_normalized="sean-labs")
    return SocialProfile.objects.create(user=user, handle=handle)


@pytest.fixture
def page(fb, user) -> ConnectedAccount:
    return ConnectedAccount.objects.create(
        user=user,
        social_profile=fb,
        provider="meta",
        external_account_id=PAGE,
        platform="facebook",
        display_name="Sean Labs",
        access_token=TOKEN,
    )


def feed(*ids: str) -> dict:
    return {
        "data": [
            {
                "id": pid,
                "message": f"post {pid}",
                "created_time": f"2026-10-2{n}T10:00:00+0000",
                "permalink_url": f"https://www.facebook.com/{pid}",
            }
            for n, pid in enumerate(ids, start=1)
        ]
    }


def insights(views: int) -> dict:
    return {
        "data": [
            {"name": "post_media_view", "values": [{"value": views}]},
            {"name": "post_total_media_view_unique", "values": [{"value": views // 2}]},
        ]
    }


def serve(providers, posts: dict, per_post: dict) -> None:
    """The Page's posts, and the insights each post answers (a Response, or the dict of a 200)."""
    table = {("GET", f"{GRAPH}/{PAGE}/posts"): httpx.Response(200, json=posts)}
    for pid, body in per_post.items():
        table[("GET", f"{GRAPH}/{pid}/insights")] = (
            body if isinstance(body, httpx.Response) else httpx.Response(200, json=body)
        )
    providers.on("meta", table)


def sync(profile_id: int, platform=None):
    return async_to_sync(DjangoOwnPostSync().sync_own_posts)(profile_id, platform)


def insight_calls(providers) -> int:
    return sum(1 for r in providers.requests("meta") if r.url.path.endswith("/insights"))


def test_the_pages_posts_and_their_views_are_stored(fb, page, providers) -> None:
    serve(providers, feed("1001_1", "1001_2"), {"1001_1": insights(120), "1001_2": insights(40)})
    out = sync(fb.pk)
    assert out["source"] == "meta" and out["platform"] == "facebook"
    assert out["stored"] == 2 and out["metrics_read"] == 2 and out["metrics_failed"] == 0
    assert out["handle"] == "sean-labs" and out["complete"] is True
    rows = Post.objects.filter(author_id=fb.handle_id).order_by("platform_post_id")
    assert [p.caption for p in rows] == ["post 1001_1", "post 1001_2"]
    views = MetricSnapshot.objects.get(post__platform_post_id="1001_1")
    assert views.views == 120
    assert (views.likes, views.comments, views.shares) == (None, None, None)  # never 0


def test_the_pass_is_recorded_with_meta_as_the_source(fb, page, providers) -> None:
    serve(providers, feed("1001_1"), {"1001_1": insights(10)})
    sync(fb.pk)
    run = IngestPass.objects.get()
    assert (run.source, run.complete, run.handle_id) == ("meta", True, fb.handle_id)


def test_a_post_whose_metrics_fail_keeps_its_row_and_no_snapshot(fb, page, providers) -> None:
    serve(
        providers,
        feed("1001_1", "1001_2"),
        {"1001_1": httpx.Response(500, json={}), "1001_2": insights(40)},
    )
    out = sync(fb.pk)
    assert out["stored"] == 2 and out["metrics_read"] == 1 and out["metrics_failed"] == 1
    assert Post.objects.filter(platform_post_id="1001_1").exists()
    assert not MetricSnapshot.objects.filter(post__platform_post_id="1001_1").exists()
    assert MetricSnapshot.objects.filter(post__platform_post_id="1001_2").exists()


def test_a_rejected_token_stops_the_metric_reads_but_keeps_the_posts(fb, page, providers) -> None:
    serve(
        providers,
        feed("1001_1", "1001_2", "1001_3"),
        {"1001_1": httpx.Response(401, json={}), "1001_2": insights(1), "1001_3": insights(1)},
    )
    out = sync(fb.pk)
    assert out["stored"] == 3 and out["metrics_failed"] == 1 and out["metrics_read"] == 0
    assert insight_calls(providers) == 1  # the other two were not tried


def test_only_the_newest_posts_get_their_metrics(fb, page, providers, monkeypatch) -> None:
    monkeypatch.setattr(own_post_sync, "META_METRICS_PER_SYNC", 1)
    serve(providers, feed("1001_1", "1001_2", "1001_3"), {"1001_1": insights(9)})
    out = sync(fb.pk)
    assert out["stored"] == 3 and out["metrics_read"] == 1 and out["metrics_failed"] == 0
    assert insight_calls(providers) == 1


def test_an_empty_read_is_stored_but_never_counts_as_a_pass(fb, page, providers) -> None:
    serve(providers, {"data": []}, {})
    out = sync(fb.pk)
    assert out["stored"] == 0 and out["complete"] is False
    assert IngestPass.objects.get().complete is False


def test_a_rejected_token_on_the_post_list_fails_the_sync(fb, page, providers) -> None:
    providers.on("meta", {("GET", f"{GRAPH}/{PAGE}/posts"): httpx.Response(401, json={})})
    with pytest.raises(ProviderAuthError):
        sync(fb.pk)
    assert Post.objects.count() == 0 and IngestPass.objects.count() == 0


def test_repeating_the_sync_adds_no_posts(fb, page, providers) -> None:
    serve(providers, feed("1001_1", "1001_2"), {"1001_1": insights(5), "1001_2": insights(6)})
    sync(fb.pk)
    sync(fb.pk)
    assert Post.objects.filter(author_id=fb.handle_id).count() == 2
    assert IngestPass.objects.count() == 2


def test_meta_is_used_only_for_a_facebook_profile(user, env, providers) -> None:
    handle = SocialHandle.objects.create(platform="x", handle_normalized="ateh")
    own = SocialProfile.objects.create(user=user, handle=handle)
    ConnectedAccount.objects.create(
        user=user,
        social_profile=own,
        provider="meta",
        external_account_id=PAGE,
        platform="facebook",
        access_token=TOKEN,
    )
    with pytest.raises(ProviderUnavailable, match="no connected x account"):
        sync(own.pk)
    assert providers.requests("meta") == []


def test_a_revoked_page_is_not_read(fb, page, providers) -> None:
    ConnectedAccount.objects.filter(pk=page.pk).update(status="revoked")
    with pytest.raises(ProviderUnavailable, match="no connected facebook account"):
        sync(fb.pk)
    assert providers.requests("meta") == []


def test_meta_wins_when_post_for_me_is_linked_too(fb, page, user, env, providers) -> None:
    env(PFM_ENV)
    ConnectedAccount.objects.create(
        user=user,
        social_profile=fb,
        provider="pfm",
        external_account_id="sa_9",
        platform="facebook",
    )
    serve(providers, feed("1001_1"), {"1001_1": insights(3)})
    assert sync(fb.pk)["source"] == "meta"
    assert providers.requests("pfm") == []


def test_an_unreadable_stored_token_says_to_connect_again(fb, page, providers, settings) -> None:
    from cryptography.fernet import Fernet

    settings.TOKEN_ENCRYPTION_KEY = Fernet.generate_key().decode()  # the key that sealed it is gone
    with pytest.raises(ProviderUnavailable, match="cannot be read"):
        sync(fb.pk)
    assert providers.requests("meta") == []


def test_the_token_never_reaches_a_stored_post_or_the_result(fb, page, providers) -> None:
    serve(providers, feed("1001_1"), {"1001_1": insights(10)})
    out = sync(fb.pk)
    assert TOKEN not in repr(out)
    assert not Post.objects.filter(caption__contains=TOKEN).exists()
