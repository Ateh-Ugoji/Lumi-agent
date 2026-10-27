"""``HandleBook`` over CONNECT's ``HandleDirectory`` and the real handle tables."""

from __future__ import annotations

from dataclasses import replace

import pytest
from asgiref.sync import async_to_sync, sync_to_async

from apps.connections.handles.directory import HandleDirectory
from apps.intelligence.repos import HandleBookRepo
from apps.profiles import services
from apps.profiles.models import HandleOrigin, SocialHandle
from lumi_ai.competitors.handles import known_pictures, remember_authors
from lumi_ai.ports import HandleBook, KnownHandle
from lumi_ai.tests.competitors.support import make_posts
from lumi_ai.tests.competitors.test_tools import _call, _services

PHOTO = "https://cdn.example/sama.jpg"


def test_it_satisfies_the_port() -> None:
    assert isinstance(HandleBookRepo(), HandleBook)


@pytest.mark.django_db
class TestOverTheTables:
    def test_accounts_a_scan_read_are_saved_with_the_niche_origin(self) -> None:
        saved = async_to_sync(HandleBookRepo().remember_scanned)(
            "x", ["Sama", "levelsio", "@sama"], origin="niche"
        )
        assert saved == 2
        row = SocialHandle.objects.get(platform="x", handle_normalized="sama")
        assert row.origin == HandleOrigin.NICHE and row.avatar_url == ""
        assert SocialHandle.objects.filter(platform="x").count() == 2

    def test_an_author_is_saved_with_the_photo_the_response_carried(self) -> None:
        async_to_sync(HandleBookRepo().remember)(
            "x", [KnownHandle("sama", PHOTO), KnownHandle("nopic")], origin="niche"
        )
        assert SocialHandle.objects.get(handle_normalized="sama").avatar_url == PHOTO
        assert SocialHandle.objects.get(handle_normalized="nopic").avatar_url == ""

    def test_a_stored_photo_is_not_replaced(self) -> None:
        book = HandleBookRepo()
        async_to_sync(book.remember)("x", [KnownHandle("sama", PHOTO)], origin="niche")
        async_to_sync(book.remember)(
            "x", [KnownHandle("sama", "https://cdn.example/new.jpg")], origin="niche"
        )
        assert SocialHandle.objects.get(handle_normalized="sama").avatar_url == PHOTO

    def test_pictures_come_back_by_lowercase_handle_and_only_when_known(self) -> None:
        book = HandleBookRepo()
        async_to_sync(book.remember)(
            "x", [KnownHandle("Sama", PHOTO), KnownHandle("nopic")], origin="niche"
        )
        found = async_to_sync(book.pictures)("x", ["SAMA", "nopic", "stranger"])
        assert dict(found) == {"sama": PHOTO}

    def test_a_handle_is_per_platform(self) -> None:
        book = HandleBookRepo()
        async_to_sync(book.remember)("x", [KnownHandle("sama", PHOTO)], origin="niche")
        assert dict(async_to_sync(book.pictures)("linkedin", ["sama"])) == {}


class DeadStore:
    async def known_keys(self, platform, handles):
        raise RuntimeError("table down")

    remember_rows = pictures = known_keys


def test_a_table_that_is_down_costs_the_scan_nothing() -> None:
    """HandleDirectory never raises and spends nothing on a lookup; the helpers add a second guard."""
    book = HandleBookRepo(HandleDirectory(DeadStore()))
    assert async_to_sync(book.remember_scanned)("x", ["a"], origin="niche") == 0
    assert async_to_sync(book.pictures)("x", ["a"]) == {}
    async_to_sync(remember_authors)(book, "x", {"a": KnownHandle("a")})
    assert async_to_sync(known_pictures)(book, "x", ["a"]) == {}


@pytest.mark.django_db(transaction=True)
async def test_the_database_and_the_answer_keep_the_stored_photo_when_the_source_brings_another() -> (
    None
):
    """The handle already has photo X; the scan's posts carry Y. Both the row and the viral post say X."""
    stored, fresh = PHOTO, "https://cdn.example/fresh.jpg"
    await sync_to_async(services.get_or_create_handle)(
        "x", "sama", origin=HandleOrigin.LIVE, avatar_url=stored
    )
    posts = [
        replace(p, author_avatar_url=fresh) for p in make_posts("sama", 3, winners=0)
    ]
    registry, *_ = _services({"sama": posts}, handles=HandleBookRepo())
    out = await _call(registry, "check_niche_trends", handles=["sama"])
    assert out["new_matches_found"] == 3
    assert {p["avatar_url"] for p in out["viral_posts"]} == {stored}
    row = await SocialHandle.objects.aget(platform="x", handle_normalized="sama")
    assert row.avatar_url == stored


@pytest.mark.django_db(transaction=True)
async def test_a_handle_with_no_stored_photo_takes_the_one_the_source_brings() -> None:
    fresh = "https://cdn.example/fresh.jpg"
    posts = [
        replace(p, author_avatar_url=fresh) for p in make_posts("sama", 2, winners=0)
    ]
    registry, *_ = _services({"sama": posts}, handles=HandleBookRepo())
    out = await _call(registry, "check_niche_trends", handles=["sama"])
    assert {p["avatar_url"] for p in out["viral_posts"]} == {fresh}
    row = await SocialHandle.objects.aget(platform="x", handle_normalized="sama")
    assert row.avatar_url == fresh
