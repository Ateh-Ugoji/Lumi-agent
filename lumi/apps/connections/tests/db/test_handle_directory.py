"""The handle directory over Postgres: pictures go through ``get_or_create_handle``."""

from __future__ import annotations

import pytest
from asgiref.sync import async_to_sync

from apps.connections.handles.directory import HandleDirectory
from apps.connections.handles.live import XpozExactUser
from apps.connections.handles.types import HandleRow
from apps.connections.stores import DjangoHandleStore
from apps.profiles import services
from apps.profiles.models import HandleOrigin, SocialHandle


def row(handle, platform="x", followers=None, name="", avatar="", source="live"):
    return HandleRow(handle, platform, name, avatar, followers, source)


class Live:
    def __init__(self, rows):
        self.rows = rows
        self.calls: list[tuple[str, str]] = []

    def supports(self, platform):
        return platform == "x"

    async def search(self, platform, query):
        self.calls.append((platform, query))
        return self.rows


def test_a_live_pull_stores_the_picture_of_a_handle_that_has_none(db) -> None:
    store = DjangoHandleStore()
    async_to_sync(store.remember_live)(
        [row("karpathy", followers=900, avatar="https://img/a.jpg")]
    )
    handle = SocialHandle.objects.get(handle_normalized="karpathy")
    assert handle.avatar_url == "https://img/a.jpg" and handle.follower_count == 900


def test_a_picture_that_is_stored_is_not_replaced_by_a_later_pull(db) -> None:
    """Fill-only is ARCHITECT's rule for ``get_or_create_handle``. A refresh service is theirs."""
    store = DjangoHandleStore()
    async_to_sync(store.remember_live)([row("karpathy", avatar="https://img/old.jpg")])
    async_to_sync(store.remember_live)(
        [row("karpathy", avatar="https://img/new.jpg", followers=5)]
    )
    handle = SocialHandle.objects.get(handle_normalized="karpathy")
    assert handle.avatar_url == "https://img/old.jpg"
    assert handle.follower_count == 5, "the rest of a live pull still lands"


def test_an_author_the_scan_knew_gets_a_picture_when_it_had_none(db) -> None:
    services.get_or_create_handle("x", "sama", origin=HandleOrigin.NICHE)
    async_to_sync(DjangoHandleStore().remember_live)(
        [row("sama", avatar="https://img/sama.jpg")]
    )
    assert SocialHandle.objects.get(handle_normalized="sama").avatar_url == (
        "https://img/sama.jpg"
    )


def test_the_directory_saves_scanned_handles_with_the_niche_origin(db) -> None:
    live = Live(
        [row("karpathy", name="Andrej", avatar="https://img/k.jpg", followers=7)]
    )
    directory = HandleDirectory(
        DjangoHandleStore(), XpozExactUser(live), enrich_limit=6
    )
    assert async_to_sync(directory.remember_scanned)(["karpathy"], origin="niche") == 1
    handle = SocialHandle.objects.get(handle_normalized="karpathy")
    assert handle.origin == "niche" and handle.avatar_url == "https://img/k.jpg"
    assert handle.display_name == "Andrej" and handle.follower_count == 7


def test_a_scan_never_lowers_the_origin_or_replaces_a_known_handle(db) -> None:
    services.get_or_create_handle(
        "x", "sama", origin=HandleOrigin.SELECTED, avatar_url="https://img/mine.jpg"
    )
    live = Live([row("sama", avatar="https://img/other.jpg")])
    directory = HandleDirectory(
        DjangoHandleStore(), XpozExactUser(live), enrich_limit=6
    )
    assert async_to_sync(directory.remember_scanned)(["sama"], origin="niche") == 0
    handle = SocialHandle.objects.get(handle_normalized="sama")
    assert handle.origin == "selected" and handle.avatar_url == "https://img/mine.jpg"
    assert live.calls == [], "a handle the store knows is never searched again"


def test_pictures_come_back_for_handles_with_a_face_only(db) -> None:
    services.get_or_create_handle(
        "x", "Karpathy", display_name="Andrej", avatar_url="https://img/k.jpg"
    )
    services.get_or_create_handle("x", "nopic")
    services.get_or_create_handle("instagram", "other", avatar_url="https://img/i.jpg")
    found = async_to_sync(HandleDirectory(DjangoHandleStore()).pictures)(
        ["KARPATHY", "nopic", "@other", "ghost"]
    )
    assert set(found) == {"karpathy"}
    assert found["karpathy"].display_name == "Andrej"
    assert found["karpathy"].avatar_url == "https://img/k.jpg"


def test_an_exact_username_match_only(db) -> None:
    live = Live(
        [
            row("karpathy_fan", avatar="https://img/fan.jpg"),
            row("Karpathy", avatar="https://img/k.jpg"),
        ]
    )
    got = async_to_sync(XpozExactUser(live).exact)("x", "@karpathy")
    assert got is not None and got.avatar_url == "https://img/k.jpg"
    none = async_to_sync(XpozExactUser(Live([row("karpathy_fan")])).exact)(
        "x", "karpathy"
    )
    assert none is None
    assert async_to_sync(XpozExactUser(live).exact)("tiktok", "karpathy") is None


def test_invalid_handles_never_stop_the_rest_of_a_batch(db) -> None:
    async_to_sync(DjangoHandleStore().remember_live)(
        [row("two words"), row("fine", avatar="https://img/f.jpg")]
    )
    assert list(SocialHandle.objects.values_list("handle_normalized", flat=True)) == [
        "fine"
    ]


@pytest.mark.parametrize("origin", ["niche", "cache"])
def test_remember_rows_is_add_if_absent_under_the_given_origin(db, origin) -> None:
    store = DjangoHandleStore()
    async_to_sync(store.remember_rows)([row("a", followers=3)], origin)
    async_to_sync(store.remember_rows)([row("a", followers=9, name="Late")], origin)
    handle = SocialHandle.objects.get(handle_normalized="a")
    assert handle.origin == origin and handle.follower_count == 3


def test_the_store_itself_returns_only_rows_with_a_picture(db) -> None:
    services.get_or_create_handle("x", "pic", avatar_url="https://img/p.jpg")
    services.get_or_create_handle("x", "nopic")
    rows = async_to_sync(DjangoHandleStore().pictures)("x", ["pic", "nopic"])
    assert [r.handle for r in rows] == ["pic"]
