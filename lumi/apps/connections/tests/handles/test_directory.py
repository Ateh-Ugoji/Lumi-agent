"""Port of ``legacy/tests/test_handle_db.py`` (the handle DB the scans fed).

Legacy names are kept in the test names so the parity map matches them.
"""

from __future__ import annotations

import pytest

from apps.connections.errors import BudgetExceeded
from apps.connections.handles.directory import HandleDirectory
from apps.connections.handles.types import HandleRow


class MemoryDirectoryStore:
    def __init__(
        self, known: dict[str, HandleRow] | None = None, *, down: bool = False
    ):
        self.rows: dict[str, HandleRow] = dict(known or {})
        self.down = down
        self.writes: list[tuple[list[HandleRow], str]] = []

    async def known_keys(self, platform, handles):
        if self.down:
            raise RuntimeError("store down")
        return {f"{platform}:{h.lower()}" for h in handles} & set(self.rows)

    async def remember_rows(self, rows, origin):
        if self.down:
            raise RuntimeError("store down")
        self.writes.append((list(rows), origin))
        for r in rows:
            self.rows.setdefault(r.key, r)

    async def pictures(self, platform, handles):
        if self.down:
            raise RuntimeError("store down")
        wanted = {h.lower() for h in handles}
        return [
            r
            for r in self.rows.values()
            if r.platform == platform and r.handle.lower() in wanted and r.avatar_url
        ]


class Lookup:
    def __init__(self, *, fail: Exception | None = None, wrong_person: bool = False):
        self.calls: list[str] = []
        self.fail = fail
        self.wrong_person = wrong_person

    async def exact(self, platform, handle):
        self.calls.append(handle)
        if self.fail:
            raise self.fail
        name = "someone_else" if self.wrong_person else handle
        return HandleRow(
            name,
            platform,
            display_name=f"{handle} dev",
            avatar_url=f"https://img/{handle}",
            followers=50,
            source="live",
        )


def row(handle, **kw):
    return HandleRow(handle, "x", **kw)


async def test_scanned_handles_enrich_only_unknown_within_cap() -> None:
    store = MemoryDirectoryStore({"x:sama": row("sama")})
    lookup = Lookup()
    directory = HandleDirectory(store, lookup, enrich_limit=1)

    written = await directory.remember_scanned(
        ["sama", "karpathy", "levelsio"], origin="niche"
    )

    assert lookup.calls == ["karpathy"], "a known handle is never completed; cap = 1"
    assert written == 2
    rows, origin = store.writes[0]
    assert origin == "niche"
    by_handle = {r.handle: r for r in rows}
    assert by_handle["karpathy"].avatar_url == "https://img/karpathy"
    assert by_handle["karpathy"].followers == 50
    assert (
        by_handle["levelsio"].avatar_url == ""
        and by_handle["levelsio"].followers is None
    )


async def test_scanned_handles_zero_limit_saves_handles_only() -> None:
    store = MemoryDirectoryStore()
    lookup = Lookup()
    directory = HandleDirectory(store, lookup, enrich_limit=0)

    assert await directory.remember_scanned(["sama"], origin="niche") == 1
    assert lookup.calls == [], "no paid lookup when the cap is 0"
    assert store.writes[0][0][0].followers is None


async def test_scanned_handles_no_enrichment_when_store_is_down() -> None:
    lookup = Lookup()
    directory = HandleDirectory(MemoryDirectoryStore(down=True), lookup, enrich_limit=6)

    assert await directory.remember_scanned(["sama"], origin="niche") == 0
    assert lookup.calls == [], "no credits when the store cannot keep the result"


async def test_a_fuzzy_top_hit_is_never_stored_as_the_handle() -> None:
    store = MemoryDirectoryStore()
    directory = HandleDirectory(store, Lookup(wrong_person=True), enrich_limit=6)

    assert await directory.remember_scanned(["karpathy"], origin="niche") == 1
    saved = store.writes[0][0][0]
    assert (
        saved.handle == "karpathy"
        and saved.avatar_url == ""
        and saved.followers is None
    )


async def test_a_failed_lookup_saves_the_handle_alone() -> None:
    store = MemoryDirectoryStore()
    lookup = Lookup(fail=BudgetExceeded("run budget"))
    directory = HandleDirectory(store, lookup, enrich_limit=6)

    assert await directory.remember_scanned(["sama", "levelsio"], origin="niche") == 2
    assert [r.avatar_url for r in store.writes[0][0]] == ["", ""]


async def test_scanned_handles_are_cleaned_and_deduplicated() -> None:
    store = MemoryDirectoryStore()
    directory = HandleDirectory(store, None, enrich_limit=6)

    written = await directory.remember_scanned(
        ["@Sama", "sama", "  ", "", "LevelsIO"], origin="niche"
    )

    assert written == 2
    assert [r.handle for r in store.writes[0][0]] == ["Sama", "LevelsIO"]


async def test_directory_remembers_scanned_and_met_authors() -> None:
    """The authors of viral AND quiet posts are saved, with the tracked accounts."""
    store = MemoryDirectoryStore()
    directory = HandleDirectory(store, None)

    await directory.remember_scanned(["sama", "levelsio"], origin="niche")
    await directory.remember(
        ["sama", "levelsio", "quiet_author", "OtherCreator"], origin="niche"
    )

    assert set(store.rows) == {
        "x:sama",
        "x:levelsio",
        "x:quiet_author",
        "x:othercreator",
    }
    assert {origin for _, origin in store.writes} == {"niche"}


async def test_directory_remembers_each_author_once() -> None:
    store = MemoryDirectoryStore()
    directory = HandleDirectory(store, None)

    new = await directory.remember(["peer_one", "peer_two", "peer_one"], origin="niche")

    assert set(store.rows) == {"x:peer_one", "x:peer_two"}
    assert new == 2


async def test_remember_counts_only_the_handles_that_were_new() -> None:
    store = MemoryDirectoryStore({"x:sama": row("sama", avatar_url="https://img/old")})
    directory = HandleDirectory(store, None)

    assert await directory.remember(["sama", "fresh"], origin="niche") == 1
    assert store.rows["x:sama"].avatar_url == "https://img/old"


@pytest.mark.parametrize("name", ["remember", "remember_scanned"])
async def test_directory_never_raises_when_the_store_is_down(name) -> None:
    directory = HandleDirectory(
        MemoryDirectoryStore(down=True), Lookup(), enrich_limit=6
    )

    assert await getattr(directory, name)(["sama"], origin="niche") == 0


async def test_lookup_returns_only_rows_that_carry_a_picture() -> None:
    store = MemoryDirectoryStore(
        {
            "x:karpathy": row(
                "Karpathy",
                display_name="Andrej",
                avatar_url="https://img/pfp.jpg",
                followers=1234,
            ),
            "x:nopic": row("nopic", display_name="No Pic"),
        }
    )
    directory = HandleDirectory(store, None)

    found = await directory.pictures(["Karpathy", "nopic", "   ", "@karpathy"])

    assert set(found) == {"karpathy"}, (
        "keys lowercased, duplicates collapsed, no picture = out"
    )
    assert found["karpathy"].avatar_url == "https://img/pfp.jpg"
    assert (
        found["karpathy"].display_name == "Andrej"
        and found["karpathy"].followers == 1234
    )


async def test_lookup_never_raises_when_the_store_is_down() -> None:
    assert (
        await HandleDirectory(MemoryDirectoryStore(down=True)).pictures(["anyone"])
        == {}
    )
    assert await HandleDirectory(MemoryDirectoryStore()).pictures([]) == {}


async def test_scan_leaves_rows_null_when_the_store_does_not_know_the_face() -> None:
    store = MemoryDirectoryStore({"x:sama": row("sama")})  # known, but with no picture

    assert await HandleDirectory(store).pictures(["sama", "stranger"]) == {}


async def test_lookup_drops_a_blank_picture_even_if_the_store_returns_one() -> None:
    class Sloppy(MemoryDirectoryStore):
        async def pictures(self, platform, handles):
            return [row("nopic"), row("pic", avatar_url="https://img/p.jpg")]

    assert set(await HandleDirectory(Sloppy()).pictures(["nopic", "pic"])) == {"pic"}
