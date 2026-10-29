# ruff: noqa: F811
"""``OwnPostSync`` dispatching on the routes table: LinkedIn, X through Xpoz, and the fall-through."""

from __future__ import annotations

from datetime import UTC, datetime

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
from lumi_ai.ports import PostIn, ProviderUnavailable

pytestmark = pytest.mark.django_db

READ_SCOPE = "r_member_social"


def profile_on(user, platform: str, handle: str) -> SocialProfile:
    row = SocialHandle.objects.create(platform=platform, handle_normalized=handle)
    return SocialProfile.objects.create(user=user, handle=row)


def connect(profile, user, *, provider: str, platform: str, status="active", scopes=()):
    return ConnectedAccount.objects.create(
        user=user,
        social_profile=profile,
        provider=provider,
        external_account_id="acct-1",
        platform=platform,
        display_name="Sean",
        access_token="tok-FAKE",
        status=status,
        scopes=list(scopes),
    )


def sync(profile_id: int):
    return async_to_sync(DjangoOwnPostSync().sync_own_posts)(profile_id, None)


def linkedin_feed() -> dict:
    return {
        "elements": [
            {
                "id": "urn:li:share:1",
                "commentary": "first",
                "publishedAt": 1761640800000,
            },
            {
                "id": "urn:li:share:2",
                "commentary": "second",
                "publishedAt": 1761727200000,
            },
        ]
    }


def test_a_linkedin_account_with_the_read_scope_stores_posts_and_no_metrics(
    user, providers
) -> None:
    li = profile_on(user, "linkedin", "sean")
    connect(li, user, provider="linkedin", platform="linkedin", scopes=[READ_SCOPE])
    providers.on(
        "linkedin", {("GET", "/rest/posts"): httpx.Response(200, json=linkedin_feed())}
    )
    out = sync(li.pk)
    assert out["source"] == "linkedin" and out["stored"] == 2
    assert out["metrics_read"] == 0 and out["metrics_failed"] == 0
    assert Post.objects.filter(author_id=li.handle_id).count() == 2
    assert (
        not MetricSnapshot.objects.exists()
    )  # LinkedIn reports none: never a fabricated 0
    assert IngestPass.objects.get().source == "linkedin"


def test_a_limited_linkedin_account_does_not_read_and_says_to_connect(
    user, providers
) -> None:
    li = profile_on(user, "linkedin", "sean")
    connect(li, user, provider="linkedin", platform="linkedin", status="limited")
    with pytest.raises(ProviderUnavailable, match="no connected linkedin account"):
        sync(li.pk)
    assert providers.requests("linkedin") == []


def test_a_limited_linkedin_account_falls_through_to_post_for_me(
    user, providers, env
) -> None:
    env(PFM_ENV)
    li = profile_on(user, "linkedin", "sean")
    connect(li, user, provider="linkedin", platform="linkedin", status="limited")
    connect(li, user, provider="pfm", platform="linkedin", scopes=[]).save()
    providers.on(
        "pfm",
        {
            ("GET", "/v1/social-account-feeds/acct-1"): httpx.Response(
                200, json={"data": []}
            )
        },
    )
    out = sync(li.pk)
    assert "source" not in out and providers.requests("linkedin") == []


class FakeXpoz:
    def __init__(self, posts: list[PostIn]) -> None:
        self.posts = posts
        self.calls: list[tuple] = []

    async def fetch_user_posts(self, platform, handle, since, limit):
        self.calls.append((platform, handle, since, limit))
        return self.posts


def x_post(pid: str, views: int) -> PostIn:
    from lumi_ai.ports import PostMetrics

    return PostIn(
        platform="x",
        external_id=pid,
        text=f"post {pid}",
        published_at=datetime(2026, 10, 20, 10, tzinfo=UTC),
        kind="original",
        source="xpoz",
        metrics=PostMetrics(views=views),
    )


def test_an_x_profile_is_read_through_xpoz_by_handle_when_it_is_live(
    user, monkeypatch
) -> None:
    monkeypatch.setenv("XPOZ_LIVE_ENABLED", "true")
    monkeypatch.setenv("XPOZ_API_KEY", "xpoz-FAKE")
    fake = FakeXpoz([x_post("1", 500), x_post("2", 7)])
    seen: dict = {}

    def data(user_id):
        seen["user_id"] = user_id
        return fake

    monkeypatch.setattr(own_post_sync, "_xpoz_data", data)
    x = profile_on(user, "x", "seanlabs")
    out = sync(x.pk)
    assert out["source"] == "xpoz" and out["stored"] == 2
    assert seen["user_id"] == user.pk
    assert fake.calls == [("x", "seanlabs", None, own_post_sync.OWN_POST_LIMIT)]
    assert MetricSnapshot.objects.get(post__platform_post_id="1").views == 500
    assert IngestPass.objects.get().source == "xpoz"
    assert {p.author_id for p in Post.objects.all()} == {x.handle_id}


def test_xpoz_off_means_x_needs_a_connected_account_like_before(
    user, monkeypatch
) -> None:
    called = []
    monkeypatch.setattr(own_post_sync, "_xpoz_data", lambda uid: called.append(uid))
    x = profile_on(user, "x", "seanlabs")
    with pytest.raises(ProviderUnavailable, match="no connected x account"):
        sync(x.pk)
    assert called == []
