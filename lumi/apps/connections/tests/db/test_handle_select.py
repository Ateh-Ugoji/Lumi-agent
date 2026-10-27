"""``POST /handles/select`` writes nothing but the handle's name.

The body comes from the browser and ``social_handles`` is read by every user, so a photo, a
display name or a follower count sent here must never reach it (CONTRATOS §11, row 30).
"""

from __future__ import annotations

import pytest
from asgiref.sync import async_to_sync

from apps.connections.handles.types import HandleRow
from apps.connections.stores import DjangoHandleStore
from apps.profiles import services
from apps.profiles.models import HandleOrigin, SocialHandle

from .test_api import client_for

pytestmark = pytest.mark.django_db

SELECT = "/api/v1/handles/select"
SAVED = "/api/v1/handles/saved"
EVIL = {
    "display_name": "SCAM",
    "avatar_url": "https://evil.example/a.png",
    "followers": 5,
}


@pytest.fixture(autouse=True)
def urls(settings):
    settings.ROOT_URLCONF = "apps.connections.tests.db.urls"


@pytest.fixture
def api(user):
    return client_for(user)


def stored(handle: str = "karpathy", platform: str = "x") -> SocialHandle:
    return SocialHandle.objects.get(platform=platform, handle_normalized=handle)


def snapshot(handle: SocialHandle) -> tuple:
    return (
        handle.handle_display,
        handle.display_name,
        handle.avatar_url,
        handle.follower_count,
        handle.origin,
    )


def test_an_empty_handle_keeps_none_of_what_the_client_sent(api) -> None:
    services.get_or_create_handle("x", "karpathy", origin=HandleOrigin.NICHE)
    response = api.post(SELECT, {"handle": "karpathy", **EVIL}, format="json")
    assert response.status_code == 200
    handle = stored()
    assert handle.avatar_url == "" and handle.display_name == ""
    assert handle.follower_count is None and handle.follower_count_at is None
    assert not handle.snapshots.exists()


def test_a_new_handle_is_created_without_any_client_data(api) -> None:
    response = api.post(SELECT, {"handle": "@KarPathy", **EVIL}, format="json")
    assert response.json() == {
        "remembered": True,
        "handle": "karpathy",
        "platform": "x",
    }
    handle = stored()
    assert (handle.avatar_url, handle.display_name, handle.follower_count) == (
        "",
        "",
        None,
    )
    assert handle.handle_display == "karpathy", (
        "the client does not pick the stored case"
    )
    assert not handle.snapshots.exists()


def test_a_handle_with_data_does_not_change_not_even_when_asked_to_overwrite(
    api,
) -> None:
    services.get_or_create_handle(
        "x",
        "karpathy",
        origin=HandleOrigin.LIVE,
        display_name="Real Name",
        avatar_url="https://img.example/real.jpg",
        follower_count=1000,
        handle_display="Karpathy",
    )
    before = snapshot(stored())
    for extra in ({}, {"overwrite": True}):
        response = api.post(
            SELECT, {"handle": "karpathy", **EVIL, **extra}, format="json"
        )
        assert response.status_code == 200
    assert snapshot(stored()) == before
    assert stored().snapshots.count() == 1, "no follower snapshot from the client"


@pytest.mark.parametrize(
    "url", ["ftp://evil.example/a.png", "javascript:alert(1)", "not a url"]
)
def test_a_url_that_is_not_http_is_ignored_and_never_stored(api, url) -> None:
    response = api.post(
        SELECT, {"handle": "karpathy", "avatar_url": url}, format="json"
    )
    assert response.status_code == 200
    assert stored().avatar_url == ""
    assert not SocialHandle.objects.filter(avatar_url__startswith="ftp").exists()


def test_a_picked_handle_is_stored_as_cache_never_live(api) -> None:
    api.post(SELECT, {"handle": "karpathy", **EVIL}, format="json")
    assert stored().origin == HandleOrigin.CACHE
    (saved,) = api.get(SAVED).json()["results"]
    assert saved["source"] == "cache"


def test_selecting_never_raises_a_handle_above_what_a_provider_gave_it(api) -> None:
    services.get_or_create_handle("x", "sama", origin=HandleOrigin.LIVE)
    api.post(SELECT, {"handle": "sama"}, format="json")
    assert stored("sama").origin == HandleOrigin.LIVE


def test_a_later_live_pull_fills_the_photo_of_a_picked_handle(api) -> None:
    api.post(SELECT, {"handle": "karpathy", **EVIL}, format="json")
    live = HandleRow(
        "karpathy",
        "x",
        "Andrej",
        "https://img.example/real.jpg",
        1000,
        "live",
    )
    async_to_sync(DjangoHandleStore().remember_live)([live])
    handle = stored()
    assert handle.avatar_url == "https://img.example/real.jpg"
    assert handle.display_name == "Andrej" and handle.follower_count == 1000
    assert handle.origin == HandleOrigin.LIVE


def test_the_platform_is_part_of_the_key(api) -> None:
    services.get_or_create_handle(
        "x", "karpathy", origin=HandleOrigin.LIVE, avatar_url="https://img/x.jpg"
    )
    api.post(
        SELECT,
        {"handle": "karpathy", "platform": "instagram", **EVIL},
        format="json",
    )
    assert stored(platform="x").avatar_url == "https://img/x.jpg"
    assert stored(platform="instagram").avatar_url == ""


def test_a_handle_that_the_platform_refuses_is_not_remembered(api) -> None:
    response = api.post(SELECT, {"handle": "a" * 16}, format="json")
    assert response.status_code == 400
    assert SocialHandle.objects.count() == 0


def test_the_stored_case_is_the_normalized_name_not_the_callers() -> None:
    DjangoHandleStore().select("x", "KarPathy")
    assert stored().handle_display == "karpathy"
