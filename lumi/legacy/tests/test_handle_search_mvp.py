"""Tests for the @-handle search MVP (mvp/handle_search/server.py).

Xpoz is fully mocked — the suite must pass with no network and zero credits.
Covers: db-first (zero-credit) path, cache reuse, prefix-chain reuse, live-on-miss,
key rotation, budget exhaustion, the select/remember path, auto-persistence of
EVERY live pull (pfp + name + followers, selected or not), and the cache-freshness
TTL (stale results re-query live in real time; fresh negative cache never re-burns),
context ranking from the words typed before the @, the half/half mix by origin —
saved half (memory-served rows, local db leading) vs live half (fresh-pull rows),
exact typed handle first, shortages backfilled so the list still fills to ten —
the combined `saved_handles`
count, and the /api/handles/saved instant-suggest snapshot (db ∪ remembered,
deduped, zero credits — the layer that paints while you type).
"""

import pytest

from mvp.handle_search import server
from mvp.handle_search.server import (
    _MemoryCollection,
    search_handles,
)


class FakeXpoz:
    """Stands in for server._xpoz_user_search. Counts calls."""

    def __init__(self, users=None):
        self.calls = 0
        self.users = users if users is not None else [
            {"username": "karpathy", "name": "Andrej",
             "profileImageUrl": "http://x/p.jpg", "followersCount": 200},
            {"username": "karpov", "name": "Karpov",
             "profileImageUrl": "http://x/q.jpg", "followersCount": 50},
            {"username": "karl", "name": "Karl",
             "profileImageUrl": "http://x/r.jpg", "followersCount": 10},
        ]

    async def __call__(self, query):
        self.calls += 1
        return [u for u in self.users if query.lower() in u["username"]]


def _set_collections(monkeypatch):
    monkeypatch.setattr(server, "_handle_cache", _MemoryCollection())
    monkeypatch.setattr(server, "_handle_mappings", _MemoryCollection())


@pytest.fixture(autouse=True)
def clean_state(monkeypatch):
    """Fresh in-memory Chroma + session + env per test."""
    _set_collections(monkeypatch)
    monkeypatch.setattr(server, "_session", {"live_queries": 0})
    monkeypatch.setenv("HANDLE_SEARCH_DB", "nonexistent.db")  # _db_handles() -> []
    monkeypatch.setenv("MVP_XPOZ_LIVE", "1")
    monkeypatch.setenv("MVP_XPOZ_BUDGET", "10")
    monkeypatch.setenv("MVP_CACHE_TTL_MINUTES", "60")
    monkeypatch.setenv("XPOZ_API_KEY", "test-key-1")
    monkeypatch.setenv("XPOZ_API_KEY_2", "test-key-2")


def _use_xpoz(monkeypatch, fake):
    monkeypatch.setattr(server, "_xpoz_user_search", fake)


def _handles(result):
    return [r["handle"] for r in result["results"]]


def _local_db(monkeypatch, tmp_path, profiles=(), authors=()):
    """Point HANDLE_SEARCH_DB at a throwaway sqlite db holding the given handles."""
    import sqlite3
    db = tmp_path / "lumi.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE profiles (handle TEXT)")
    con.execute("CREATE TABLE listening_matches (author_handle TEXT)")
    for h in profiles:
        con.execute("INSERT INTO profiles VALUES (?)", (h,))
    for a in authors:
        con.execute("INSERT INTO listening_matches VALUES (?)", (a,))
    con.commit()
    con.close()
    monkeypatch.setenv("HANDLE_SEARCH_DB", str(db))


# --- zero-credit paths -------------------------------------------------------

async def test_short_query_is_min_length_and_never_calls_xpoz(monkeypatch):
    fake = FakeXpoz()
    _use_xpoz(monkeypatch, fake)
    result = await search_handles("@k")
    assert result["reason"] == "min_length"
    assert result["results"] == []
    assert result["live"] is False
    assert fake.calls == 0


async def test_db_hits_do_not_gate_the_live_search(monkeypatch, tmp_path):
    """The handle DB is a head START, not the answer: db rows merge in, but the
    real search still fires — otherwise '@ateh' would only ever show the one Ateh
    saved in the db instead of the actual people on X right now."""
    import sqlite3
    db = tmp_path / "lumi.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE profiles (handle TEXT)")
    con.execute("INSERT INTO profiles VALUES ('karpathy')")
    con.execute("CREATE TABLE listening_matches (author_handle TEXT)")
    con.execute("INSERT INTO listening_matches VALUES ('kardashev')")  # not in live results
    con.commit()
    con.close()
    monkeypatch.setenv("HANDLE_SEARCH_DB", str(db))

    fake = FakeXpoz()  # returns karpathy, karpov, karl for q="kar"
    _use_xpoz(monkeypatch, fake)
    result = await search_handles("@kar")

    assert fake.calls == 1, "db hits must not suppress the live search"
    assert result["live"] is True
    # db + live merged: the db-only handle survives alongside actual search data
    assert set(_handles(result)) == {"karpathy", "karpov", "karl", "kardashev"}
    by = {r["handle"]: r["source"] for r in result["results"]}
    assert by["kardashev"] == "db", "db-only rows still show"
    assert by["karl"] == "live"
    assert by["karpathy"] == "live", "live data upgrades the shared row (pfp/followers)"
    assert result["refreshed"] is False, "nothing was stale — this is a fresh pull"


async def test_db_known_handle_is_pinned_near_the_top(monkeypatch, tmp_path):
    """A local-db row (followers NULL) keeps a reserved slot at the top of the
    saved half even when every live candidate has a bigger follower count — otherwise
    @ateh buries AtehOfficial behind ten strangers and off the top-10 cut, so the
    one handle you actually know vanishes from the mix. The saved half is short here
    (1), so live backfills the rest of the ten."""
    import sqlite3
    db = tmp_path / "lumi.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE profiles (handle TEXT)")
    con.execute("INSERT INTO profiles VALUES ('karpathy')")  # db-only, not in live results
    con.commit()
    con.close()
    monkeypatch.setenv("HANDLE_SEARCH_DB", str(db))

    # 12 high-follower strangers, none named karpathy → without the pin the
    # db row (followers NULL) ranks dead last and falls off the top-10 cut.
    fake = FakeXpoz(users=[
        {"username": f"kar{i}", "name": f"Stranger {i}",
         "profileImageUrl": "", "followersCount": 10000 - i}
        for i in range(12)
    ])
    _use_xpoz(monkeypatch, fake)

    result = await search_handles("@kar")
    handles = _handles(result)

    assert len(handles) == 10, "the top-10 window still applies"
    assert "karpathy" in handles, "db-known handle must survive the cut"
    assert handles[0] == "karpathy", "no exact match here → pinned to the very top"
    # the mix survives: live rows still fill every remaining slot
    assert sum(1 for r in result["results"] if r["source"] == "live") >= 9


async def test_db_pin_survives_richer_remembered_overwrite(monkeypatch, tmp_path):
    """The production @ateh case: the db handle is ALSO in the remembered store,
    so the merge overwrites source="db" with a richer cache copy (pfp + followers).
    The split is by origin — a cache copy is memory-served, hence saved half — and a
    local-db handle is membership-kept there too, so the upgraded row must not sink
    behind higher-follower strangers and off the [:10] cut."""
    import sqlite3
    db = tmp_path / "lumi.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE profiles (handle TEXT)")
    con.execute("INSERT INTO profiles VALUES ('karpathy')")
    con.commit()
    con.close()
    monkeypatch.setenv("HANDLE_SEARCH_DB", str(db))

    # remembered store holds a richer karpathy (source upgrades to "cache",
    # followers 1717 — but 1717 still loses to ten 10k strangers without the pin)
    from mvp.handle_search.server import SelectHandle, _mapping_put
    _mapping_put(SelectHandle(handle="karpathy", display_name="Andrej",
                              followers=1717).model_dump())

    fake = FakeXpoz(users=[
        {"username": f"kar{i}", "name": f"Stranger {i}",
         "profileImageUrl": "", "followersCount": 10000 - i}
        for i in range(12)
    ])
    _use_xpoz(monkeypatch, fake)

    result = await search_handles("@kar")
    handles = _handles(result)
    by = {r["handle"]: r for r in result["results"]}

    assert "karpathy" in handles, "db-known handle must survive even after source upgrade"
    assert handles[0] == "karpathy", "saved half leads: memory-served + db membership"
    # richer data won the row, but it's still a db-known handle
    assert by["karpathy"]["source"] in ("cache", "live"), "row upgraded from the db copy"
    assert by["karpathy"]["followers"] == 1717, "remembered followers are kept"


async def test_half_and_half_mix_when_both_sides_are_full(monkeypatch, tmp_path):
    """The core 50/50 rule: with >=5 known and >=5 live, the dropdown shows 5 from
    the local db and 5 live — a known handle never crowds out the actual people on
    X, and live never buries every handle we already have."""
    db_handles = [f"kar{i}x" for i in range(6)]  # 6 known, all prefix "@kar"
    _local_db(monkeypatch, tmp_path, profiles=db_handles)
    live = [f"kar{i}z" for i in range(10)]  # 10 strangers, none of them known
    _use_xpoz(monkeypatch, FakeXpoz(users=[
        {"username": h, "name": h.title(),
         "profileImageUrl": "", "followersCount": 1000 - i}
        for i, h in enumerate(live)
    ]))

    result = await search_handles("@kar")
    handles = _handles(result)
    known = [h for h in handles if h in db_handles]
    others = [h for h in handles if h not in db_handles]

    assert len(handles) == 10
    assert len(known) == 5 and len(others) == 5, "both sides full → exactly half/half"
    assert handles[0] in db_handles, "the db half leads the list"


async def test_exact_db_match_leads_but_still_shows_the_live_half(monkeypatch, tmp_path):
    """Typing an exact db handle (@karl) puts it at the top WITHOUT collapsing the
    list to all-db — the other half still shows live candidates, so you can tag a
    different Karl instead of only the one you already have."""
    db_handles = ["karl"] + [f"karl{c}" for c in "abcdef"]  # 7 known starting with karl
    _local_db(monkeypatch, tmp_path, profiles=db_handles)
    live = ["karlson", "karlos", "karlito", "karlx", "karly",
            "karlz", "karlk", "karlj", "karln", "karlm"]
    _use_xpoz(monkeypatch, FakeXpoz(users=[
        {"username": h, "name": h.title(), "profileImageUrl": "",
         "followersCount": 5000 - i}
        for i, h in enumerate(live)
    ]))

    result = await search_handles("@karl")
    handles = _handles(result)
    known = [h for h in handles if h in db_handles]
    others = [h for h in handles if h not in db_handles]

    assert handles[0] == "karl", "the exact typed handle leads the whole list"
    assert len(known) == 5 and len(others) == 5, "exact db match still shows the live half"


async def test_short_live_side_backfills_with_extra_known_handles(monkeypatch, tmp_path):
    """When live only finds 2 fresh people, the list still fills to ten: known
    handles take the leftover slots (beyond their usual five) instead of the
    dropdown going short."""
    db_handles = [f"kar{c}" for c in "abcdefgh"]  # 8 known
    _local_db(monkeypatch, tmp_path, profiles=db_handles)
    live = ["karx", "kary"]  # only 2 fresh people
    _use_xpoz(monkeypatch, FakeXpoz(users=[
        {"username": h, "name": h.title(), "profileImageUrl": "",
         "followersCount": 100}
        for h in live
    ]))

    result = await search_handles("@kar")
    handles = _handles(result)
    known = [h for h in handles if h in db_handles]
    others = [h for h in handles if h not in db_handles]

    assert len(handles) == 10, "a short side never shortens the list"
    assert len(known) == 8 and len(others) == 2, "known fills the leftover slots"


async def test_remembered_rows_fill_the_saved_half_without_lumi_db(monkeypatch, tmp_path):
    """The split is saved-vs-fresh, not sqlite-vs-the-rest: the bar's own memory
    (handle_mappings) counts as the saved half even when lumi.db has nothing, and
    the fresh pull's never-seen handles take the live half — so the mix reads
    'already seen vs brand-new' either way."""
    _local_db(monkeypatch, tmp_path, profiles=[])  # empty local db
    remembered = [f"kar{i}r" for i in range(6)]  # 6 seen before, prefix "@kar"
    from mvp.handle_search.server import SelectHandle, _mapping_put
    for h in remembered:
        _mapping_put(SelectHandle(handle=h, display_name=h.title(),
                                  followers=50).model_dump())
    live = [f"kar{i}z" for i in range(10)]  # 10 never-seen handles
    _use_xpoz(monkeypatch, FakeXpoz(users=[
        {"username": h, "name": h.title(), "profileImageUrl": "",
         "followersCount": 1000 - i}
        for i, h in enumerate(live)
    ]))

    result = await search_handles("@kar")
    handles = _handles(result)
    saved = [h for h in handles if h in remembered]
    fresh = [h for h in handles if h not in remembered]

    assert len(handles) == 10
    assert len(saved) == 5 and len(fresh) == 5, "memory-served vs fresh-pull halves"
    assert handles[0] in remembered, "the saved half leads the list"


async def test_db_serves_free_when_live_is_unavailable(monkeypatch, tmp_path):
    """Live off / budget spent → known handles still answer, at zero credits.
    That's the db's real job: a help layered on, never a dependency."""
    import sqlite3
    db = tmp_path / "lumi.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE profiles (handle TEXT)")
    con.execute("INSERT INTO profiles VALUES ('karpathy'), ('karpov')")
    con.commit()
    con.close()
    monkeypatch.setenv("HANDLE_SEARCH_DB", str(db))
    monkeypatch.setenv("MVP_XPOZ_LIVE", "0")

    fake = FakeXpoz()
    _use_xpoz(monkeypatch, fake)
    result = await search_handles("@kar")

    assert fake.calls == 0, "live disabled → no credits spent"
    assert result["live"] is False
    assert result["reason"] == "live_disabled"
    assert set(_handles(result)) == {"karpathy", "karpov"}
    assert all(r["source"] == "db" for r in result["results"])


# --- live-on-miss + cache reuse ---------------------------------------------

async def test_live_on_miss_then_cached(monkeypatch):
    fake = FakeXpoz()
    _use_xpoz(monkeypatch, fake)

    first = await search_handles("@karpathy")
    assert first["live"] is True
    assert "karpathy" in _handles(first)
    assert fake.calls == 1

    second = await search_handles("@karpathy")
    assert fake.calls == 1, "identical query must be served from cache, not re-burned"
    assert second["live"] is False
    assert second["refreshed"] is False
    assert "karpathy" in _handles(second)


async def test_prefix_chain_reuses_cache(monkeypatch):
    fake = FakeXpoz()
    _use_xpoz(monkeypatch, fake)

    first = await search_handles("@ka")  # broad -> live
    assert first["live"] is True
    assert fake.calls == 1

    # Narrowing (ka -> karp) should reuse the broad cache, not spend another query.
    second = await search_handles("@karp")
    assert fake.calls == 1, "narrowing a cached prefix must reuse cache"
    assert second["live"] is False
    assert "karpathy" in _handles(second)
    assert "karpov" in _handles(second)


async def test_results_deduped_and_exact_match_first(monkeypatch):
    fake = FakeXpoz(users=[
        {"username": "karl", "name": "Karl", "profileImageUrl": "", "followersCount": 999},
        {"username": "karpathy", "name": "Andrej", "profileImageUrl": "", "followersCount": 1},
    ])
    _use_xpoz(monkeypatch, fake)
    result = await search_handles("@karl")
    assert _handles(result)[0] == "karl", "exact match sorts before higher-follower partials"
    assert len(_handles(result)) == len(set(_handles(result)))


async def test_followers_null_when_unknown(monkeypatch):
    fake = FakeXpoz(users=[{"username": "karl", "name": "K", "profileImageUrl": "", "followersCount": None}])
    _use_xpoz(monkeypatch, fake)
    result = await search_handles("@karl")
    assert result["results"][0]["followers"] is None, "unknown followers must be NULL, never 0"


# --- auto-persistence: every pulled handle moves into the handle DB ----------

async def test_every_live_pull_saved_to_handle_db_without_selection(monkeypatch):
    fake = FakeXpoz()  # 3 users for "kar"; the user never selects anyone
    _use_xpoz(monkeypatch, fake)

    result = await search_handles("@kar")
    assert result["live"] is True
    assert len(result["results"]) == 3

    metas = {m["handle"].lower(): m
             for m in server._cache_get_all(server._handle_mappings)}
    assert set(metas) == {"karpathy", "karpov", "karl"}, "every pulled handle is saved"
    assert metas["karpathy"]["avatar_url"] == "http://x/p.jpg"
    assert metas["karpathy"]["display_name"] == "Andrej"
    assert metas["karpathy"]["followers"] == 200
    assert all(m["origin"] == "live" for m in metas.values())


class EvolvingXpoz:
    """Returns growing follower counts so tests can tell stale from fresh data."""

    def __init__(self):
        self.calls = 0

    async def __call__(self, query):
        self.calls += 1
        return [{"username": "karl", "name": "Karl",
                 "profileImageUrl": "http://x/k.jpg",
                 "followersCount": 100 * self.calls}]


async def test_stale_cache_triggers_realtime_refresh(monkeypatch):
    monkeypatch.setenv("MVP_CACHE_TTL_MINUTES", "0")  # everything is stale instantly
    fake = EvolvingXpoz()
    _use_xpoz(monkeypatch, fake)

    first = await search_handles("@karl")
    assert first["live"] is True
    assert first["refreshed"] is False
    assert first["results"][0]["followers"] == 100
    assert fake.calls == 1

    second = await search_handles("@karl")
    assert fake.calls == 2, "stale cached results must re-query live, not lock to cache"
    assert second["live"] is True
    assert second["refreshed"] is True
    assert second["results"][0]["followers"] == 200, "fresh pull replaces stale data"
    assert second["results"][0]["source"] == "live"

    # the refreshed data also lands in the handle DB
    metas = {m["handle"].lower(): m
             for m in server._cache_get_all(server._handle_mappings)}
    assert metas["karl"]["followers"] == 200
    assert metas["karl"]["origin"] == "live"


async def test_negative_cache_not_reburned_when_fresh(monkeypatch):
    fake = FakeXpoz(users=[])  # live search legitimately finds nothing
    _use_xpoz(monkeypatch, fake)

    first = await search_handles("@zebra")
    assert first["live"] is True
    assert first["results"] == []

    second = await search_handles("@zebra")
    assert fake.calls == 1, "a fresh empty cache entry must not re-burn credits"
    assert second["reason"] == "cache_exact"
    assert second["live"] is False


async def test_cache_paint_matches_live_paint_for_contains_matches(monkeypatch):
    """Xpoz returns handles containing the query ("notnaval" for "naval") — the
    cached re-paint must show the same set as the live pull, not fewer."""
    fake = FakeXpoz(users=[
        {"username": "naval", "name": "N", "profileImageUrl": "", "followersCount": 5},
        {"username": "notnaval", "name": "NN", "profileImageUrl": "", "followersCount": 3},
    ])
    _use_xpoz(monkeypatch, fake)

    first = await search_handles("@naval")
    assert first["live"] is True
    assert set(_handles(first)) == {"naval", "notnaval"}

    second = await search_handles("@naval")
    assert fake.calls == 1
    assert set(_handles(second)) == {"naval", "notnaval"}


async def test_re_served_cache_handles_keep_their_origin(monkeypatch):
    """A handle already in the handle DB is never re-persisted from the cache path
    (it would lose its original origin label)."""
    fake = FakeXpoz(users=[
        {"username": "notnaval", "name": "NN", "profileImageUrl": "http://x/n.jpg",
         "followersCount": 7},
    ])
    _use_xpoz(monkeypatch, fake)

    first = await search_handles("@naval")  # live pull -> persisted origin=live
    assert first["live"] is True

    def _origins():
        return {m["handle"].lower(): m["origin"]
                for m in server._cache_get_all(server._handle_mappings)}

    assert _origins() == {"notnaval": "live"}

    second = await search_handles("@naval")  # served via contains-cache, not mappings
    assert second["live"] is False
    assert _origins() == {"notnaval": "live"}, "re-serving must not relabel a remembered handle"


async def test_new_handle_from_cache_pull_is_persisted(monkeypatch):
    """A brand-new handle that surfaces from a CACHE re-serve (no live call) still
    lands in handle_mappings with origin="cache" — so every cache pull, not just
    every live pull, keeps expanding the handle DB."""
    # seed handle_cache directly with a result set, leaving handle_mappings EMPTY
    # (simulates a handle the browser saw but that was never persisted before)
    server._cache_put_search("zephyr", [
        {"handle": "zephyr", "display_name": "Zeph",
         "avatar_url": "http://x/z.jpg", "followers": 42, "source": "live"},
        {"handle": "zephyr_lab", "display_name": "Lab",
         "avatar_url": "", "followers": 9, "source": "live"},
    ])
    # mappings must be empty → the cache pull is the only thing that can persist
    assert server._cache_get_all(server._handle_mappings) == []

    fake = FakeXpoz(users=[])  # must NOT go live — cache has fresh coverage
    _use_xpoz(monkeypatch, fake)

    result = await search_handles("@zephyr")
    assert fake.calls == 0, "fresh cached answer must skip the live call"
    assert result["live"] is False
    assert {_h for _h in _handles(result)} >= {"zephyr", "zephyr_lab"}

    metas = {m["handle"].lower(): m
             for m in server._cache_get_all(server._handle_mappings)}
    assert set(metas) == {"zephyr", "zephyr_lab"}, "cache-pulled handles are persisted"
    assert all(m["origin"] == "cache" for m in metas.values()), \
        "persisted from the cache path → honest origin=cache"
    assert metas["zephyr"]["followers"] == 42, "pfp/name/followers carried through"


# --- budget + live-disable ---------------------------------------------------

async def test_budget_exhaustion_blocks_live(monkeypatch):
    monkeypatch.setenv("MVP_XPOZ_BUDGET", "2")  # exactly one X query (2 credits)
    fake = FakeXpoz()
    _use_xpoz(monkeypatch, fake)

    await search_handles("@karl")   # spends the whole credit budget
    result = await search_handles("@zebra")  # different query, no cache
    assert fake.calls == 1
    assert result["live"] is False
    assert result["reason"] == "budget_exhausted"
    assert result["credits_spent_this_session"] == 2


async def test_live_disabled(monkeypatch):
    monkeypatch.setenv("MVP_XPOZ_LIVE", "0")
    fake = FakeXpoz()
    _use_xpoz(monkeypatch, fake)
    result = await search_handles("@karl")
    assert fake.calls == 0
    assert result["reason"] == "live_disabled"


async def test_stale_refresh_blocked_by_budget_still_serves_stale(monkeypatch):
    monkeypatch.setenv("MVP_CACHE_TTL_MINUTES", "0")
    monkeypatch.setenv("MVP_XPOZ_BUDGET", "2")  # exactly one X query (2 credits)
    fake = FakeXpoz()
    _use_xpoz(monkeypatch, fake)

    await search_handles("@karpathy")  # spends the single budgeted query
    result = await search_handles("@karpathy")
    assert fake.calls == 1
    assert result["live"] is False
    assert result["reason"] == "budget_exhausted"
    assert "karpathy" in _handles(result), "stale results are still served as fallback"


# --- key rotation ------------------------------------------------------------

async def test_key_rotation_on_auth_failure(monkeypatch):
    """_xpoz_user_search rotates key1 -> key2 on a 401; the search still succeeds."""
    attempted = []

    async def fake_user_search(query):
        # Simulate the real rotation logic by calling through httpx-free stub.
        keys = server._xpoz_keys()
        for key in keys:
            attempted.append(key)
            if key.endswith("1"):  # first key "fails" auth
                continue
            return [{"username": "karl", "name": "K", "profileImageUrl": "",
                     "followersCount": 1}]
        return []

    _use_xpoz(monkeypatch, fake_user_search)
    result = await search_handles("@karl")
    assert attempted[0] == "test-key-1"
    assert "test-key-2" in attempted, "must fall through to the second key"
    assert "karl" in _handles(result)


# --- select / remember -------------------------------------------------------

async def test_select_remembers_handle_for_later_search(monkeypatch):
    from mvp.handle_search.server import SelectHandle, _mapping_put

    _mapping_put(SelectHandle(handle="Karpathy", display_name="Andrej",
                              followers=200, selected_query="kar").model_dump())

    fake = FakeXpoz(users=[])  # live returns nothing -> remembered handle still surfaces
    _use_xpoz(monkeypatch, fake)
    result = await search_handles("@karpathy")
    assert result["results"][0]["handle"].lower() == "karpathy"
    assert result["results"][0]["source"] == "cache"
    # a selection is recorded with its own origin in the handle DB
    metas = {m["handle"].lower(): m
             for m in server._cache_get_all(server._handle_mappings)}
    assert metas["karpathy"]["origin"] == "selected"


# --- context ranking + saved-handles union ----------------------------------

async def test_context_words_re_rank_results(monkeypatch):
    """The up-to-3 words before the @ are sent as `context` and boost ranking."""
    fake = FakeXpoz(users=[
        {"username": "karpathy", "name": "Andrej Karpathy",
         "profileImageUrl": "", "followersCount": 200},
        {"username": "karll", "name": "Karl Logistics",
         "profileImageUrl": "", "followersCount": 500},
    ])
    _use_xpoz(monkeypatch, fake)

    plain = await search_handles("@kar")
    assert _handles(plain)[0] == "karll", "without context, higher followers win"

    ctx = await search_handles("@kar", context="founder openai karpathy")
    assert ctx["context"] == "founder openai karpathy"
    assert _handles(ctx)[0] == "karpathy", "context word in the name boosts it to top"


async def test_context_is_capped_at_three_words(monkeypatch):
    fake = FakeXpoz(users=[{"username": "karl", "name": "K",
                            "profileImageUrl": "", "followersCount": 1}])
    _use_xpoz(monkeypatch, fake)
    result = await search_handles("@karl", context="alpha beta gamma delta epsilon")
    # server keeps the first 3 words of whatever context it receives
    assert result["context"] == "alpha beta gamma"


async def test_saved_handles_unions_db_and_remembered(monkeypatch, tmp_path):
    """`saved_handles` = distinct handles across local DB + remembered store."""
    import sqlite3
    db = tmp_path / "lumi.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE profiles (handle TEXT)")
    con.execute("INSERT INTO profiles VALUES ('karpathy'), ('ateh')")
    con.commit()
    con.close()
    monkeypatch.setenv("HANDLE_SEARCH_DB", str(db))

    # remember one handle that is NOT in the local db (dup is harmless)
    from mvp.handle_search.server import SelectHandle, _mapping_put
    _mapping_put(SelectHandle(handle="karl", followers=1).model_dump())
    _mapping_put(SelectHandle(handle="ateh").model_dump())  # dup of a db handle

    stats = await server.api_stats()
    import json as _json
    payload = _json.loads(stats.body)
    # db has {karpathy, ateh}, remembered adds {karl} -> union of 3
    assert payload["saved_handles"] == 3
    assert payload["known_db_handles"] == 2
    assert payload["remembered_handles"] == 2


# --- instant-suggest snapshot (/api/handles/saved) ----------------------------

async def test_saved_endpoint_unions_db_and_remembered(monkeypatch, tmp_path):
    """Snapshot for the per-keystroke suggest layer: db + remembered, deduped,
    followers first, db rows winning the dedup so origin labels stay honest."""
    import sqlite3

    db = tmp_path / "lumi.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE profiles (handle TEXT)")
    con.execute("INSERT INTO profiles VALUES ('karpathy'), ('AtehOfficial')")
    con.commit()
    con.close()
    monkeypatch.setenv("HANDLE_SEARCH_DB", str(db))

    from mvp.handle_search.server import SelectHandle, _mapping_put
    _mapping_put(SelectHandle(handle="karl", display_name="Karl",
                              followers=500).model_dump())
    _mapping_put(SelectHandle(handle="atehofficial", followers=9).model_dump())

    payload = await server.api_saved()
    by_handle = {r["handle"].lower(): r for r in payload["results"]}
    assert sorted(by_handle) == ["atehofficial", "karl", "karpathy"], "dup collapses"
    assert payload["count"] == 3
    assert by_handle["karpathy"]["source"] == "db"
    assert by_handle["atehofficial"]["source"] == "db"  # db side wins the dedup
    assert by_handle["karl"]["source"] == "cache"
    assert payload["results"][0]["handle"].lower() == "karl", "known followers lead"


async def test_saved_endpoint_never_spends_credits(monkeypatch):
    """The snapshot is read-only db + remembered — no Xpoz, no writes."""
    fake = FakeXpoz()
    _use_xpoz(monkeypatch, fake)
    payload = await server.api_saved()
    assert payload["results"] == []
    assert payload["count"] == 0
    assert fake.calls == 0
