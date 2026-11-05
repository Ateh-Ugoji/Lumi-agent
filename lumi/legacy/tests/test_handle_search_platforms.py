"""Cross-platform @-handle search tests (the platform-selector fan-out).

Xpoz is fully mocked at the `_xpoz_get` seam — the suite must pass with no
network and zero credits. Covers: per-platform fan-out with each endpoint's
exact path/param, per-platform field normalization, cache isolation between
platforms, the X-only local-db layer, the honest LinkedIn no-provider path,
a credit budget stopping a fan-out mid-way, `platforms` CSV validation,
platform-filtered /api/handles/saved, the platform catalog in stats, the
default-X stamp on every legacy-shaped row, and both Chroma Cloud quota
fixes that keep real usage honest: the metadata-value trim that keeps fat
(Instagram-sized) pulls cacheable, and the offset paging that reads past
the 300-row Get quota.
"""

import json

import pytest

from mvp.handle_search import server
from mvp.handle_search.server import (
    _MemoryCollection,
    _parse_platforms,
    search_handles,
)

TWITTER = "/api/data/twitter/users/live"
INSTAGRAM = "/api/data/instagram/users/live"
TIKTOK = "/api/data/tiktok/users/live"
REDDIT = "/api/data/reddit/users/live"


class FakeXpozGet:
    """Stands in for server._xpoz_get (the httpx seam): records (path, params)
    per call and answers with platform-shaped raw user objects."""

    def __init__(self, users_by_path=None):
        self.calls: list[tuple[str, dict]] = []
        self.users_by_path = users_by_path or {}

    async def __call__(self, path, params):
        self.calls.append((path, dict(params)))
        return self.users_by_path.get(path, [])


def _set_collections(monkeypatch):
    monkeypatch.setattr(server, "_handle_cache", _MemoryCollection())
    monkeypatch.setattr(server, "_handle_mappings", _MemoryCollection())


@pytest.fixture(autouse=True)
def clean_state(monkeypatch):
    """Fresh in-memory Chroma + session + env per test."""
    _set_collections(monkeypatch)
    monkeypatch.setattr(server, "_session",
                         {"live_queries": 0, "credits_spent": 0})
    monkeypatch.setenv("HANDLE_SEARCH_DB", "nonexistent.db")
    monkeypatch.setenv("MVP_XPOZ_LIVE", "1")
    monkeypatch.setenv("MVP_XPOZ_BUDGET", "100")
    monkeypatch.setenv("MVP_CACHE_TTL_MINUTES", "60")
    monkeypatch.setenv("XPOZ_API_KEY", "test-key-1")
    monkeypatch.setenv("XPOZ_API_KEY_2", "test-key-2")


def _use_xpoz_get(monkeypatch, fake):
    monkeypatch.setattr(server, "_xpoz_get", fake)


# --- platforms CSV -----------------------------------------------------------

def test_parse_platforms_validation():
    assert _parse_platforms(None) == ["x"]
    assert _parse_platforms("") == ["x"]
    assert _parse_platforms("bogus") == ["x"], "unknown-only input falls back to X"
    assert _parse_platforms(" X ,instagram,X ") == ["x", "instagram"], "deduped, normalized"
    assert _parse_platforms("linkedin,unknown,tiktok") == ["linkedin", "tiktok"]


async def test_default_search_stamps_platform_x(monkeypatch):
    """Legacy shape (no platforms param) behaves exactly as before, with every
    row stamped platform=x."""
    fake = FakeXpozGet({TWITTER: [{"username": "karl", "name": "K",
                                   "profileImageUrl": "", "followersCount": 1}]})
    _use_xpoz_get(monkeypatch, fake)

    result = await search_handles("@karl")

    assert result["platforms"] == ["x"]
    assert all(r["platform"] == "x" for r in result["results"])
    assert result["reason"] is None


# --- multi-platform fan-out --------------------------------------------------

async def test_fanout_uses_each_platforms_endpoint_and_params(monkeypatch):
    """One search over four selected platforms hits four endpoints — each with
    its own query param (X/Reddit `q`, Instagram/TikTok `name`) and field set —
    stamps every row with its platform, and charges the summed credits."""
    fake = FakeXpozGet({
        TWITTER: [{"username": "karx", "name": "KX",
                   "profileImageUrl": "", "followersCount": 10}],
        REDDIT: [{"username": "kar_r"}],
        TIKTOK: [{"username": "kartk", "nickname": "TT",
                  "avatar": "", "followerCount": 7}],
        INSTAGRAM: [{"username": "kargram", "fullName": "KG",
                     "profilePicUrl": "", "followerCount": 9}],
    })
    _use_xpoz_get(monkeypatch, fake)

    result = await search_handles("@kar", platforms="x,reddit,tiktok,instagram")

    assert [c[0] for c in fake.calls] == [TWITTER, REDDIT, TIKTOK, INSTAGRAM], \
        "one live call per selected platform, in selection order"
    params = {c[0]: c[1] for c in fake.calls}
    assert params[TWITTER]["q"] == "kar"
    assert params[REDDIT]["q"] == "kar"
    assert params[INSTAGRAM]["name"] == "kar", "Instagram queries by name"
    assert params[TIKTOK]["name"] == "kar", "TikTok queries by name"
    assert all(c[1].get("fields") for c in fake.calls)

    assert result["platforms"] == ["x", "reddit", "tiktok", "instagram"]
    assert {r["platform"] for r in result["results"]} == \
        {"x", "reddit", "tiktok", "instagram"}
    assert result["platform_reasons"] == {
        "x": None, "reddit": None, "tiktok": None, "instagram": None}
    assert result["live"] is True
    assert result["live_queries_this_session"] == 4
    assert result["credits_spent_this_session"] == 21, "X 2 + Reddit 2 + TikTok 5 + Instagram 12"


async def test_per_platform_field_normalization(monkeypatch):
    """Each platform names its fields differently; rows normalize onto one shape.
    Reddit has no display name and no follower count — both stay honest (empty /
    NULL), karma is never relabeled as followers."""
    fake = FakeXpozGet({
        INSTAGRAM: [{"username": "kg", "fullName": "Gram Person",
                     "profilePicUrl": "http://i/p.jpg", "followerCount": 55}],
        REDDIT: [{"username": "redd_k", "profilePicUrl": "http://r/p.jpg",
                  "totalKarma": 999}],
        TIKTOK: [{"username": "tt", "nickname": "Tik Nick",
                  "avatar": "http://t/a.jpg", "followerCount": 3}],
    })
    _use_xpoz_get(monkeypatch, fake)

    ig = (await search_handles("@kg", platforms="instagram"))["results"][0]
    assert ig["handle"] == "kg"
    assert ig["display_name"] == "Gram Person"
    assert ig["avatar_url"] == "http://i/p.jpg"
    assert ig["followers"] == 55
    assert ig["platform"] == "instagram"

    rd = (await search_handles("@redd", platforms="reddit"))["results"][0]
    assert rd["handle"] == "redd_k"
    assert rd["display_name"] == "", "Reddit has no display name — empty, not invented"
    assert rd["followers"] is None, "karma is NOT followers — NULL, never 0"
    assert rd["avatar_url"] == "http://r/p.jpg"

    tt = (await search_handles("@tt", platforms="tiktok"))["results"][0]
    assert tt["display_name"] == "Tik Nick"
    assert tt["followers"] == 3


# --- platform isolation ------------------------------------------------------

async def test_cache_is_isolated_per_platform(monkeypatch):
    """A fresh X cache entry never answers an Instagram query (and vice versa);
    each platform's own repeat is served free from its own cache."""
    fake = FakeXpozGet({
        TWITTER: [{"username": "karx", "name": "KX",
                   "profileImageUrl": "", "followersCount": 1}],
        INSTAGRAM: [{"username": "karg", "fullName": "KG",
                     "profilePicUrl": "", "followerCount": 2}],
    })
    _use_xpoz_get(monkeypatch, fake)

    first = await search_handles("@kar", platforms="x")
    assert first["live"] is True and len(fake.calls) == 1

    second = await search_handles("@kar", platforms="instagram")
    assert len(fake.calls) == 2, "the fresh X cache must not gate the IG search"
    assert second["live"] is True
    assert all(r["platform"] == "instagram" for r in second["results"])

    third = await search_handles("@kar", platforms="instagram")
    assert len(fake.calls) == 2, "the Instagram cache answers its own repeat free"
    assert third["live"] is False


async def test_local_db_layer_only_feeds_x(monkeypatch, tmp_path):
    """lumi.db holds X handles — it is a head start for X searches only, and it
    never gates the live search on any platform."""
    import sqlite3
    db = tmp_path / "lumi.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE profiles (handle TEXT)")
    con.execute("INSERT INTO profiles VALUES ('karl')")
    con.commit()
    con.close()
    monkeypatch.setenv("HANDLE_SEARCH_DB", str(db))

    fake = FakeXpozGet({TWITTER: [], INSTAGRAM: []})
    _use_xpoz_get(monkeypatch, fake)

    x = await search_handles("@kar", platforms="x")
    assert "karl" in [r["handle"] for r in x["results"]], "db head start shows on X"
    assert x["live"] is True, "db never gates the live search"

    ig = await search_handles("@kar", platforms="instagram")
    assert "karl" not in [r["handle"] for r in ig["results"]], "X db rows are not Instagram rows"
    assert ig["live"] is True


async def test_linkedin_is_honest_no_provider(monkeypatch):
    """LinkedIn has no Xpoz endpoint: no request is made, no credits are spent,
    and the response says so — never a fabricated live source."""
    fake = FakeXpozGet({})
    _use_xpoz_get(monkeypatch, fake)

    result = await search_handles("@kar", platforms="linkedin")

    assert fake.calls == [], "no provider -> no request"
    assert result["live"] is False
    assert result["reason"] == "unsupported"
    assert result["platform_reasons"] == {"linkedin": "unsupported"}
    assert result["credits_spent_this_session"] == 0
    assert result["results"] == []


async def test_mixed_selection_reports_per_platform_reasons(monkeypatch):
    """x + linkedin together: X runs live, LinkedIn stays honestly unsupported."""
    fake = FakeXpozGet({TWITTER: [{"username": "karl", "name": "K",
                                   "profileImageUrl": "", "followersCount": 1}]})
    _use_xpoz_get(monkeypatch, fake)

    result = await search_handles("@kar", platforms="x,linkedin")

    assert [c[0] for c in fake.calls] == [TWITTER]
    assert result["platform_reasons"] == {"x": None, "linkedin": "unsupported"}
    assert result["live"] is True
    assert result["credits_spent_this_session"] == 2


# --- credit budget -----------------------------------------------------------

async def test_credit_budget_stops_expensive_platform_mid_fanout(monkeypatch):
    """Budget of 5 credits: X (2) fits, TikTok (5) would need 2+5 > 5 — the
    fan-out stops there with an honest per-platform reason, having spent only
    what it actually ran."""
    monkeypatch.setenv("MVP_XPOZ_BUDGET", "5")
    fake = FakeXpozGet({
        TWITTER: [{"username": "karl", "name": "K",
                   "profileImageUrl": "", "followersCount": 1}],
        TIKTOK: [{"username": "kartt", "nickname": "TT",
                  "avatar": "", "followerCount": 1}],
    })
    _use_xpoz_get(monkeypatch, fake)

    result = await search_handles("@kar", platforms="x,tiktok")

    assert [c[0] for c in fake.calls] == [TWITTER], "TikTok never fired"
    assert result["platform_reasons"] == {"x": None, "tiktok": "budget_exhausted"}
    assert result["reason"] == "budget_exhausted"
    assert result["live"] is True, "X still ran"
    assert result["credits_spent_this_session"] == 2
    assert {r["platform"] for r in result["results"]} == {"x"}


# --- /api/handles/saved + stats ----------------------------------------------

async def test_saved_filters_by_platform(monkeypatch):
    from mvp.handle_search.server import SelectHandle, _mapping_put

    _mapping_put(SelectHandle(handle="Karlst").model_dump())  # default x
    _mapping_put(SelectHandle(handle="kg", platform="instagram").model_dump())

    only_ig = await server.api_saved(platforms="instagram")
    assert [r["handle"].lower() for r in only_ig["results"]] == ["kg"]
    assert only_ig["results"][0]["platform"] == "instagram"

    both = await server.api_saved(platforms="x,instagram")
    assert sorted(r["handle"].lower() for r in both["results"]) == ["karlst", "kg"]


async def test_stats_exposes_the_platform_catalog():
    import json as _json

    payload = _json.loads((await server.api_stats()).body)
    by = {p["id"]: p for p in payload["available_platforms"]}
    assert list(by) == ["x", "instagram", "tiktok", "reddit", "linkedin"]
    assert by["instagram"]["credits"] == 12 and by["instagram"]["live"] is True
    assert by["linkedin"]["live"] is False
    assert payload["credits_spent_this_session"] == 0
    assert payload["live_budget"] == 100, "budget is reported in credits"


class _QuotaCollection(_MemoryCollection):
    """Reproduces Chroma Cloud's `MetadataValueSizeBytes` quota (8182): any single
    metadata value over the limit makes upsert fail — exactly what killed the
    Instagram cache entry in production on 2026-10-25."""

    LIMIT = 8182

    def upsert(self, ids, documents, metadatas):
        for meta in metadatas:
            for value in meta.values():
                if isinstance(value, str) and len(value) > self.LIMIT:
                    raise RuntimeError(
                        "Quota exceeded: 'Size of metadata dictionary value (bytes)'"
                    )
        super().upsert(ids, documents, metadatas)


def test_fat_pull_is_trimmed_into_the_cache_quota(monkeypatch):
    """A 40-row live pull (~12 KB of JSON) must be TRIMMED to fit the quota, never
    rejected — a rejected write means the cache entry never exists and the next
    search sees no fresh answer."""
    quota_coll = _QuotaCollection()
    monkeypatch.setattr(server, "_handle_cache", quota_coll)

    fat = [
        server._result(
            f"glowup_{i}",
            f"Person Number {i}",
            "https://cdninstagram.com/image?_nc_cat=" + "x" * 150,
            10_000 + i,
            "live",
            "instagram",
        )
        for i in range(40)
    ]
    server._cache_put_search("glowup", fat, platform="instagram")

    entries = [
        m for m in server._cache_get_all(quota_coll)
        if m.get("platform") == "instagram"
    ]
    assert entries, "a quota-sized pull must still land as a cache entry"
    stored = json.loads(entries[0]["results_json"])
    assert 1 <= len(stored) < 40, "rows were trimmed to fit"
    assert all(r["handle"].startswith("glowup") for r in stored)
    assert "source" not in stored[0], "slim rows: source/platform re-added on read"

    # the entry is immediately usable as fresh coverage for its platform
    reused, fresh_exact = server._cache_reuse("glowup", ["instagram"])
    assert fresh_exact["instagram"] is True, "fresh exact entry answers the query"
    assert reused and all(plat == "instagram" for _, _, plat in reused)
    assert all(row["platform"] == "instagram" for row, _, _ in reused)


async def test_fat_instagram_fanout_never_reburns_credits(monkeypatch):
    """End-to-end regression of the live 2026-10-25 bug: a 25-row Instagram pull
    exceeds the Chroma metadata quota; if its cache write is rejected, every later
    search re-fires the 12-credit live query. With the trim, the repeat is free."""
    quota_coll = _QuotaCollection()
    monkeypatch.setattr(server, "_handle_cache", quota_coll)

    ig_users = [
        {
            "username": f"glowup_{i}",
            "fullName": f"Person Number {i}",
            "profilePicUrl": "https://cdninstagram.com/p/" + "y" * 200,
            "followerCount": 5_000 + i,
        }
        for i in range(25)
    ]
    fake = FakeXpozGet({INSTAGRAM: ig_users})
    _use_xpoz_get(monkeypatch, fake)

    first = await search_handles("glowup", platforms="instagram")
    assert first["live"] is True
    assert server._session["credits_spent"] == 12
    assert len(first["results"]) <= 10

    second = await search_handles("glowup", platforms="instagram")
    assert second["live"] is False, "fresh cache must skip the live call"
    assert server._session["credits_spent"] == 12, "repeat search costs 0 credits"
    assert len(fake.calls) == 1, "exactly one live query in total"


class _GetQuotaCollection(_MemoryCollection):
    """Reproduces Chroma Cloud's `LimitValue` Get quota: `limit` must be ≤ 300,
    and an unfiltered get() silently returns only the first 300 rows — the read
    truncation seen live 2026-10-25 (count()=637, get()=300)."""

    LIMIT = 300

    def get(self, include=None, limit=None, offset=None):
        if limit is not None and limit > self.LIMIT:
            raise RuntimeError("Quota exceeded: 'Limit value' (max 300)")
        effective = self.LIMIT if limit is None else limit
        return super().get(include=include, limit=effective, offset=offset)


def test_cache_read_pages_past_the_300_row_get_quota():
    """`_cache_get_all` must page with offset/limit≤300: an unfiltered get()
    stops at 300 rows, which would hide every newer handle from the saved
    snapshot, the remembered-handle merge and stats — and once handle_cache
    itself passed 300 entries, fresh cache rows would go invisible and each
    search would re-burn credits."""
    coll = _GetQuotaCollection()
    n = 750  # past the quota, like the real 637-row handle_mappings collection
    coll.upsert(
        ids=[f"x:h{i}" for i in range(n)],
        documents=[f"h{i}" for i in range(n)],
        metadatas=[
            {"handle": f"h{i}", "platform": "x", "origin": "live"} for i in range(n)
        ],
    )
    rows = server._cache_get_all(coll)
    assert len(rows) == n, "every row must be read, not just the first 300"
    assert rows[0]["handle"] == "h0" and rows[-1]["handle"] == f"h{n - 1}"
