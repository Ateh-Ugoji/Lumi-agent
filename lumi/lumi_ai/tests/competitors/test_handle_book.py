"""What the niche scan and the framework search teach the shared handle directory.

The four sites: ``check_niche_trends`` saves the accounts it read and every author its posts
surfaced (with the photo the source gave), and takes a photo for a viral post from the directory;
``discover_and_extract_niche_frameworks`` saves every author its search surfaced and the peers it
analysed. The directory is a help, never a dependency: when it fails the answer is unchanged.
"""

from __future__ import annotations

from dataclasses import replace

from lumi_ai.ports import HandleBook, KnownHandle
from lumi_ai.tests.competitors.support import make_posts
from lumi_ai.tests.competitors.test_tools import HANDLES, _call, _services

PHOTO = "https://cdn.example/photo.jpg"


class Book:
    def __init__(self, pictures=None, fail=False):
        self.scanned: list[tuple[str, list[str], str]] = []
        self.remembered: list[tuple[str, list[KnownHandle], str]] = []
        self.asked: list[list[str]] = []
        self._pictures = pictures or {}
        self._fail = fail

    async def remember_scanned(self, platform, handles, *, origin):
        if self._fail:
            raise RuntimeError("handle table down")
        self.scanned.append((platform, list(handles), origin))
        return len(handles)

    async def remember(self, platform, handles, *, origin):
        if self._fail:
            raise RuntimeError("handle table down")
        self.remembered.append((platform, list(handles), origin))
        return len(handles)

    async def pictures(self, platform, handles):
        if self._fail:
            raise RuntimeError("handle table down")
        self.asked.append(list(handles))
        return {
            h: self._pictures[h] for h in map(str.lower, handles) if h in self._pictures
        }


def _by_name(book: Book) -> dict[str, str]:
    return {h.handle: h.avatar_url for _, hs, _ in book.remembered for h in hs}


def test_the_book_is_a_port() -> None:
    assert isinstance(Book(), HandleBook)


async def test_trends_save_every_account_they_read() -> None:
    book = Book()
    registry, *_ = _services(
        {h: make_posts(h, 3, winners=0) for h in ("sama", "levelsio")}, handles=book
    )
    out = await _call(registry, "check_niche_trends", handles=["sama", "levelsio"])
    assert out["new_matches_found"] == 6
    assert book.scanned == [("x", ["sama", "levelsio"], "niche")]


async def test_trends_save_the_authors_of_viral_and_quiet_posts_alike() -> None:
    posts = make_posts("sama", 3, winners=0)
    quiet = replace(
        posts[1],
        author_handle="quiet_author",
        metrics=replace(posts[1].metrics, likes=1),
    )
    other = replace(posts[2], author_handle="OtherCreator")
    book = Book()
    registry, *_ = _services({"sama": [posts[0], quiet, other]}, handles=book)
    await _call(registry, "check_niche_trends", handles=["sama"], min_likes=20)
    ((platform, authors, origin),) = book.remembered
    assert (platform, origin) == ("x", "niche")
    assert {a.handle for a in authors} == {"sama", "quiet_author", "OtherCreator"}


async def test_trends_hand_over_the_photo_the_source_gave_and_nothing_else() -> None:
    posts = make_posts("sama", 2, winners=0)
    with_photo = replace(posts[0], author_avatar_url=PHOTO)
    book = Book()
    registry, *_ = _services(
        {"sama": [with_photo, replace(posts[1], author_handle="nopic")]}, handles=book
    )
    await _call(registry, "check_niche_trends", handles=["sama"])
    assert _by_name(book) == {"sama": PHOTO, "nopic": ""}  # unknown stays empty


async def test_an_author_keeps_the_first_photo_any_of_their_posts_carried() -> None:
    posts = make_posts("sama", 3, winners=0)
    mixed = [posts[0], replace(posts[1], author_avatar_url=PHOTO), posts[2]]
    book = Book()
    registry, *_ = _services({"sama": mixed}, handles=book)
    await _call(registry, "check_niche_trends", handles=["sama"])
    assert _by_name(book) == {"sama": PHOTO}
    assert len(book.remembered[0][1]) == 1  # one entry per author


async def test_the_directory_photo_fills_a_viral_post_that_has_none() -> None:
    book = Book(pictures={"sama": PHOTO})
    registry, *_ = _services({"sama": make_posts("sama", 2, winners=0)}, handles=book)
    out = await _call(registry, "check_niche_trends", handles=["sama"])
    assert {p["avatar_url"] for p in out["viral_posts"]} == {PHOTO}
    assert book.asked == [["sama"]], (
        "one free lookup for the whole page, no provider call"
    )


async def test_the_stored_photo_wins_over_the_one_the_source_gave() -> None:
    posts = [
        replace(p, author_avatar_url="https://cdn.example/fresh.jpg")
        for p in make_posts("sama", 2, winners=0)
    ]
    book = Book(pictures={"sama": PHOTO})
    registry, *_ = _services({"sama": posts}, handles=book)
    out = await _call(registry, "check_niche_trends", handles=["sama"])
    assert {p["avatar_url"] for p in out["viral_posts"]} == {PHOTO}


async def test_the_source_photo_stands_only_when_nothing_is_stored() -> None:
    posts = [
        replace(p, author_avatar_url="https://cdn.example/fresh.jpg")
        for p in make_posts("sama", 2, winners=0)
    ]
    registry, *_ = _services({"sama": posts}, handles=Book(pictures={"other": PHOTO}))
    out = await _call(registry, "check_niche_trends", handles=["sama"])
    assert {p["avatar_url"] for p in out["viral_posts"]} == {
        "https://cdn.example/fresh.jpg"
    }


async def test_a_directory_that_knows_no_photo_leaves_it_empty() -> None:
    registry, *_ = _services({"sama": make_posts("sama", 2, winners=0)}, handles=Book())
    out = await _call(registry, "check_niche_trends", handles=["sama"])
    assert {p["avatar_url"] for p in out["viral_posts"]} == {""}


async def test_trends_survive_a_directory_that_is_down() -> None:
    posts = {"sama": make_posts("sama", 3, winners=0)}
    with_book, *_ = _services(posts, handles=Book(fail=True))
    without_book, *_ = _services(posts)
    broken = await _call(with_book, "check_niche_trends", handles=["sama"])
    plain = await _call(without_book, "check_niche_trends", handles=["sama"])
    assert broken == plain and broken["new_matches_found"] == 3


async def test_discovery_saves_every_author_the_search_surfaced_and_the_peers_it_read() -> (
    None
):
    found = make_posts("alice", 3) + make_posts("bob", 2) + make_posts("zed", 1)
    found = [replace(found[0], author_avatar_url=PHOTO), *found[1:]]
    posts = {h: make_posts(h, winners=5) for h in HANDLES}
    posts["search"] = found
    book = Book()
    registry, *_ = _services(posts, handles=book)
    out = await _call(
        registry, "discover_and_extract_niche_frameworks", query="AI tools"
    )
    assert out["handles_from_search"]
    assert _by_name(book) == {"alice": PHOTO, "bob": "", "zed": ""}, (
        "authors the search surfaced are saved even when they are not chosen as peers"
    )
    assert book.remembered[0][2] == "niche"
    ((platform, scanned, origin),) = book.scanned
    assert (platform, origin) == ("x", "niche")
    assert set(scanned) == set(out["scanned_handles"]) and scanned


async def test_discovery_with_given_handles_saves_the_peers_it_read() -> None:
    book = Book()
    registry, *_ = _services(handles=book)
    out = await _call(
        registry,
        "discover_and_extract_niche_frameworks",
        query="ai tools",
        handles=["alice", "bob"],
    )
    assert book.remembered == []  # nothing was searched, so no authors were surfaced
    assert book.scanned == [("x", ["alice", "bob"], "niche")] and out["status"] == "ok"


async def test_discovery_survives_a_directory_that_is_down() -> None:
    posts = {h: make_posts(h, winners=5) for h in HANDLES}
    posts["search"] = make_posts("alice", 3) + make_posts("bob", 2)
    broken, *_ = _services(posts, handles=Book(fail=True))
    plain, *_ = _services(posts)
    args = {"query": "AI tools"}
    a = await _call(broken, "discover_and_extract_niche_frameworks", **args)
    b = await _call(plain, "discover_and_extract_niche_frameworks", **args)
    a.pop("report_id"), b.pop("report_id")
    assert a == b and a["status"] == "ok"
