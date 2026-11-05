"""Port of the pass bookkeeping tests of ``tests/test_profile_extract_fixes.py`` (area 6)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from apps.connections.passes import (
    StoredPost,
    finalize_pass,
    is_second_miss,
    pass_reached_window,
)

T0 = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)
H = timedelta(hours=1)


def test_second_miss_requires_two_complete_misses() -> None:
    published = T0 - timedelta(days=2)
    ok = {
        "now": T0,
        "pass_complete": True,
        "oldest_fetched": published - timedelta(days=1),
        "newest_fetched": T0,
    }
    # second consecutive miss: last seen before the previous pass started
    assert is_second_miss(T0 - 6 * H, T0 - 3 * H, published, **ok) is True
    # first miss: last seen at the previous pass
    assert is_second_miss(T0 - 3 * H, T0 - 3 * H, published, **ok) is False
    # an incomplete pass never counts
    assert (
        is_second_miss(
            T0 - 6 * H, T0 - 3 * H, published, **dict(ok, pass_complete=False)
        )
        is False
    )
    # never seen: two misses cannot be proved
    assert is_second_miss(None, T0 - 3 * H, published, **ok) is False
    # first pass ever
    assert is_second_miss(T0 - 6 * H, None, published, **ok) is False
    # undated post
    assert is_second_miss(T0 - 6 * H, T0 - 3 * H, None, **ok) is False


def test_second_miss_bracket_and_window_guards() -> None:
    published = T0 - timedelta(days=2)
    base = {"now": T0, "pass_complete": True}
    args = (T0 - 6 * H, T0 - 3 * H)
    # the slice does not span the post's date
    unspanned = dict(base, oldest_fetched=published + H, newest_fetched=T0)
    assert is_second_miss(*args, published, **unspanned) is False
    same_edge = dict(base, oldest_fetched=published, newest_fetched=T0)
    assert is_second_miss(*args, published, **same_edge) is False
    # no window information: conservative no
    no_window = dict(base, oldest_fetched=None, newest_fetched=None)
    assert is_second_miss(*args, published, **no_window) is False
    # older than 30 days: outside the tracking window
    old = T0 - timedelta(days=40)
    spanned = dict(base, oldest_fetched=old - timedelta(days=1), newest_fetched=T0)
    assert is_second_miss(*args, old, **spanned) is False
    exactly = T0 - timedelta(days=30)
    edge = dict(base, oldest_fetched=exactly - timedelta(days=1), newest_fetched=T0)
    assert is_second_miss(*args, exactly, **edge) is True, (
        "30 days exactly is still tracked"
    )


def test_pass_reached_window() -> None:
    assert pass_reached_window(None, now=T0) is False
    assert pass_reached_window(T0 - timedelta(days=10), now=T0) is False
    assert pass_reached_window(T0 - timedelta(days=30), now=T0) is False
    assert pass_reached_window(T0 - timedelta(days=31), now=T0) is True


class MemoryPassStore:
    def __init__(self, posts: list[StoredPost]) -> None:
        self.stored = {p.key: p for p in posts}
        self.passes: list[tuple[datetime, str, bool]] = []

    async def last_complete_pass(self, handle_id, before):
        done = [s for s, _, c in self.passes if c and s < before]
        return max(done) if done else None

    async def posts(self, handle_id):
        return list(self.stored.values())

    async def save_pass(
        self, handle_id, *, started_at, source, complete, seen, flag, clear
    ):
        self.passes.append((started_at, source, complete))
        for key in seen:
            self.stored[key] = _with(self.stored[key], last_seen_at=started_at)
        for key in flag:
            self.stored[key] = _with(self.stored[key], suspect=True)
        for key in clear:
            self.stored[key] = _with(self.stored[key], suspect=False)


def _with(post: StoredPost, **changes) -> StoredPost:
    data = {
        "key": post.key,
        "external_id": post.external_id,
        "published_at": post.published_at,
        "last_seen_at": post.last_seen_at,
        "suspect": post.suspect,
    } | changes
    return StoredPost(**data)


def _post(key=1, external="p1", *, days=2, last_seen=None, suspect=False) -> StoredPost:
    return StoredPost(key, external, T0 - timedelta(days=days), last_seen, suspect)


async def _pass(store, at, fetched, *, complete=True, window="spans"):
    published = T0 - timedelta(days=2)
    spans = (published - timedelta(days=1), at)
    return await finalize_pass(
        store,
        7,
        fetched_ids=fetched,
        source="xpoz",
        pass_started=at,
        pass_complete=complete,
        fetched_window=spans if window == "spans" else None,
    )


async def test_finalize_ingest_pass_two_miss_flow() -> None:
    store = MemoryPassStore([_post()])

    r1 = await _pass(store, T0 - H, {"p1"})
    assert (r1.seen, r1.flagged_deleted) == (1, 0)
    assert store.stored[1].last_seen_at == T0 - H

    r2 = await _pass(store, T0 + H, set())  # first complete miss
    assert r2.flagged_deleted == 0 and store.stored[1].suspect is False

    r3 = await _pass(store, T0 + 3 * H, set())  # second one
    assert r3.flagged_deleted == 1 and store.stored[1].suspect is True

    r4 = await _pass(store, T0 + 5 * H, set())  # already flagged: not flagged twice
    assert r4.flagged_deleted == 0 and store.stored[1].suspect is True


async def test_an_interrupted_pass_is_not_the_first_miss() -> None:
    store = MemoryPassStore([_post()])
    await _pass(store, T0 - H, {"p1"})
    await _pass(store, T0 + H, set(), complete=False)  # cut short: proves nothing
    r3 = await _pass(store, T0 + 3 * H, set())
    assert r3.flagged_deleted == 0, "the previous COMPLETE pass saw the post"
    r4 = await _pass(store, T0 + 5 * H, set())
    assert r4.flagged_deleted == 1


async def test_a_pass_without_a_window_flags_nothing() -> None:
    store = MemoryPassStore([_post(last_seen=T0 - 9 * H)])
    store.passes.append((T0 - 3 * H, "xpoz", True))
    assert (await _pass(store, T0, set(), window="none")).flagged_deleted == 0


async def test_a_flagged_post_that_comes_back_is_cleared() -> None:
    store = MemoryPassStore([_post(suspect=True, last_seen=T0 - 9 * H)])
    result = await _pass(store, T0, {"p1"})
    assert result.cleared == 1 and store.stored[1].suspect is False


async def test_an_unrelated_miss_leaves_posts_it_did_not_cover_alone() -> None:
    old = _post(2, "old", days=20, last_seen=T0 - 9 * H)
    store = MemoryPassStore([old])
    store.passes.append((T0 - 3 * H, "xpoz", True))
    published = old.published_at
    result = await finalize_pass(
        store,
        7,
        fetched_ids=set(),
        source="xpoz",
        pass_started=T0,
        pass_complete=True,
        fetched_window=(published + H, T0),  # only reached 20 days minus an hour back
    )
    assert result.flagged_deleted == 0


@pytest.mark.parametrize("complete", [True, False])
async def test_every_pass_is_recorded(complete) -> None:
    store = MemoryPassStore([])
    await _pass(store, T0, set(), complete=complete)
    assert store.passes == [(T0, "xpoz", complete)]
