"""Standalone @-handle autocomplete MVP (side project — wired into the main Lumi app via app/routers/handles.py).

Cache-first, credit-aware handle search — but never locked to cache:

1. local DB (lumi.db, read-only)  — zero credits (X handles only)
2. Chroma handle_mappings          — every handle ever PULLED or selected
                                     (pfp + name + followers), permanent memory
3. Chroma handle_cache             — past search results + prefix-chain reuse,
                                     fresh for MVP_CACHE_TTL_MINUTES (default 60)
4. Xpoz users/live (per platform)  — whenever there is no FRESH cached answer
                                     for THAT platform (miss or stale → real-time
                                     refresh), credit-budget-guarded, key-rotated

Cross-platform: a multi-select `platforms` param (CSV, default "x") runs the
whole pipeline per selected platform — X, Instagram, TikTok, Reddit have live
search on Xpoz (2 / 12 / 5 / 2 credits per query), LinkedIn has NO provider and
stays an honest db/remembered-only platform. Every result row carries
`platform`; caches, the remembered store, and the local-db layer are all
platform-filtered (pre-existing rows default to X — that is all that existed).
`MVP_XPOZ_BUDGET` is a CREDIT budget (default 100), not a query count.

Layers 1–2 are a HEAD START, never the answer: db/remembered rows merge into the
results (and paint instantly client-side), but only a fresh cache entry — a real
recent search — may skip the live call. Otherwise "@ateh" would show only the one
Ateh saved in the db instead of the actual people currently on X. The dropdown is a
half-and-half mix by WHERE each handle came from on this search: about half the slots
go to the SAVED half — everything served from memory (local db / remembered rows /
past-search cache), with the local-db handles (e.g. @AtehOfficial) leading it — and
half to the LIVE half, the handles a fresh Xpoz pull just found that the bar has never
seen. A side short of half hands its leftover slots to the other so the list still
fills to ten, and the exact handle you typed stays at the very top. So a known handle
like @AtehOfficial is always visible beside fresh results instead of sinking behind
higher-follower strangers — and a memory-served handle can never crowd a fresh-pull
one out of view, because they now sit in different halves. When live is off or the
budget is spent, the saved half still answers: it is the help, not the source.

Every live pull is written back to handle_mappings — ALL results with their
pfp/display name/follower count, not just the one the user selected — so the
handle DB keeps expanding with every search.

Config comes from env only (`.env`, gitignored): XPOZ_API_KEY, XPOZ_API_KEY_2,
MVP_CHROMA_API_KEY, MVP_CHROMA_TENANT, MVP_CHROMA_DATABASE, MVP_XPOZ_BUDGET,
MVP_XPOZ_LIVE, MVP_CACHE_TTL_MINUTES, HANDLE_SEARCH_DB. No secrets in code, ever.

Run:  uv run uvicorn mvp.handle_search.server:app --port 8010
"""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import time
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

log = logging.getLogger("handle_search")

XPOZ_BASE = "https://api.xpoz.ai"
XPOZ_USER_FIELDS = "username,name,profileImageUrl,followersCount"
MIN_QUERY_LEN = 2
# Credit budget per server session (env MVP_XPOZ_BUDGET), in CREDITS: a live call
# costs its platform's price (X 2 / Reddit 2 / TikTok 5 / Instagram 12), so the
# meter must count credits — query-count budgeting would let one Instagram search
# burn 12 credits against a "10" that meant something else.
DEFAULT_LIVE_BUDGET = 100
DEFAULT_CACHE_TTL_MINUTES = 60  # cached results go stale after this → real-time re-query
# The dropdown is a 50/50 mix by origin: ~half the slots go to the SAVED half
# (memory-served rows — local db, remembered, cache — with local-db handles leading),
# ~half to the LIVE half (a fresh pull's genuinely-new handles). Shortages backfill —
# a side with fewer than MIX_HALF hands its leftover slots to the other — so the list
# still fills to MIX_TOTAL instead of showing a short result set.
MIX_HALF = 5
MIX_TOTAL = 10
DEFAULT_PLATFORM = "x"
# Cross-platform selector registry — every entry verified against Xpoz's live
# OpenAPI spec (https://api.xpoz.ai/openapi.json), not guessed:
#   path/param/fields differ per platform (X+Reddit take `q`, Instagram+TikTok
#   take `name`; follower/name/avatar fields are named differently each).
# LinkedIn has NO endpoint there (the spec covers Twitter/X, Instagram, Reddit,
# TikTok only) — it stays selectable as an honest db/remembered-only platform
# (live=False), never a fabricated live source. Credits per live query from
# Xpoz's pricing page: X 2 · Reddit 2 · TikTok 5 · Instagram 12.
PLATFORMS: dict[str, dict[str, Any]] = {
    "x": {
        "label": "X", "live": True, "path": "twitter", "param": "q", "credits": 2,
        "fields": "username,name,profileImageUrl,followersCount",
        "handle": "username", "name": "name",
        "avatar": "profileImageUrl", "followers": "followersCount",
    },
    "instagram": {
        "label": "Instagram", "live": True, "path": "instagram", "param": "name",
        "credits": 12, "fields": "username,fullName,profilePicUrl,followerCount",
        "handle": "username", "name": "fullName",
        "avatar": "profilePicUrl", "followers": "followerCount",
    },
    "tiktok": {
        "label": "TikTok", "live": True, "path": "tiktok", "param": "name",
        "credits": 5, "fields": "username,nickname,avatar,followerCount",
        "handle": "username", "name": "nickname",
        "avatar": "avatar", "followers": "followerCount",
    },
    "reddit": {
        "label": "Reddit", "live": True, "path": "reddit", "param": "q",
        "credits": 2,
        # Reddit has no display name and no follower count — karma is NOT
        # followers, so followers stays NULL (never a fabricated 0).
        "fields": "username,profilePicUrl",
        "handle": "username", "name": None,
        "avatar": "profilePicUrl", "followers": None,
    },
    "linkedin": {
        # No LinkedIn on Xpoz — reachable only through db/remembered rows.
        "label": "LinkedIn", "live": False, "credits": 0,
    },
}
LUMI_ROOT = Path(__file__).resolve().parents[2]
STATIC_DIR = Path(__file__).resolve().parent / "static"


def _load_dotenv() -> None:
    """Minimal .env loader (keeps the MVP decoupled from app.config's required keys)."""
    env_path = LUMI_ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv()


class _MemoryCollection:
    """Chroma-compatible subset (add/upsert/get) for offline degradation + tests."""

    def __init__(self) -> None:
        self._docs: dict[str, dict] = {}

    def add(self, ids, documents, metadatas):
        self.upsert(ids, documents, metadatas)

    def upsert(self, ids, documents, metadatas):
        for doc_id, doc, meta in zip(ids, documents, metadatas, strict=True):
            self._docs[doc_id] = {"document": doc, "metadata": meta}

    def get(self, include=None, limit=None, offset=None):
        ids = list(self._docs)
        if offset:
            ids = ids[offset:]
        if limit is not None:
            ids = ids[:limit]
        return {
            "ids": ids,
            "metadatas": [self._docs[i]["metadata"] for i in ids],
        }


_handle_cache: Any = None
_handle_mappings: Any = None


def _collections() -> tuple[Any, Any]:
    """Lazily init Chroma Cloud collections; degrade to in-memory on any failure."""
    global _handle_cache, _handle_mappings
    if _handle_cache is not None and _handle_mappings is not None:
        return _handle_cache, _handle_mappings
    api_key = os.environ.get("MVP_CHROMA_API_KEY")
    tenant = os.environ.get("MVP_CHROMA_TENANT")
    database = os.environ.get("MVP_CHROMA_DATABASE")
    if api_key and tenant and database:
        try:
            import chromadb

            client = chromadb.CloudClient(api_key=api_key, tenant=tenant, database=database)
            _handle_cache = client.get_or_create_collection("handle_cache")
            _handle_mappings = client.get_or_create_collection("handle_mappings")
            log.info("Chroma Cloud ready (database=%s)", database)
            return _handle_cache, _handle_mappings
        except Exception as exc:  # noqa: BLE001 — degrade, never hard-depend on Chroma
            log.warning("Chroma Cloud unavailable (%s); falling back to memory", exc)
    _handle_cache = _MemoryCollection()
    _handle_mappings = _MemoryCollection()
    return _handle_cache, _handle_mappings


# Chroma Cloud's free-tier `Get` quota caps `limit` at 300 rows ("LimitValue"):
# an unfiltered collection.get() silently returns only the FIRST 300 rows. The
# handle DB really held 637 rows while get() kept handing back 300 (seen live
# 2026-10-25) — hiding every newly pulled handle from the saved snapshot, the
# remembered-handle merge and stats. And once `handle_cache` itself passed 300
# entries, fresh cache rows would have gone invisible and re-burned credits on
# every search. Always page with offset until a short page arrives.
_GET_PAGE_LIMIT = 300


def _cache_get_all(collection: Any) -> list[dict]:
    """Every metadata row of a collection, paged past the 300-row Get quota."""
    metadatas: list[dict] = []
    offset = 0
    try:
        while True:
            payload = collection.get(
                include=["metadatas"], limit=_GET_PAGE_LIMIT, offset=offset
            )
            page = payload.get("metadatas") or []
            metadatas.extend(m for m in page if isinstance(m, dict))
            if len(page) < _GET_PAGE_LIMIT:
                break
            offset += len(page)
    except Exception as exc:  # noqa: BLE001
        # partial pages beat nothing: the rows we did read are a head start
        log.warning("cache read failed after %d row(s) (%s)", len(metadatas), exc)
    return metadatas


def _entry_fresh(meta: dict) -> bool:
    """True when a cached search entry is younger than the TTL.

    Stale entries no longer block a live re-query — they trigger a budget-guarded
    real-time refresh instead of serving frozen results forever."""
    try:
        ts = int(meta.get("ts") or 0)
    except (TypeError, ValueError):
        return False
    return (time.time() - ts) < _cache_ttl_minutes() * 60


# Chroma Cloud caps a single metadata VALUE at 8182 bytes ("MetadataValueSizeBytes"
# quota). A fat live pull (Instagram returns a couple of dozen rows ≈ 14 KB of JSON)
# used to fail the write silently → no cache entry → the NEXT search saw no fresh
# answer and re-burned that platform's 12 credits, forever. Stored rows are trimmed
# from the tail (least-relevant) until the blob fits with margin, so the write
# always succeeds and the credit-saving cache actually exists.
_CACHE_VALUE_BUDGET = 7000


def _cache_put_search(query: str, results: list[dict],
                      platform: str = DEFAULT_PLATFORM) -> None:
    collection, _ = _collections()
    # Stored rows only need these four fields — `source`/`platform` are re-added on
    # read (`_cache_reuse` stamps platform from the entry metadata) — so the blob
    # stays as small as the quota allows.
    slim = [
        {"handle": r.get("handle") or "",
         "display_name": r.get("display_name") or "",
         "avatar_url": r.get("avatar_url") or "",
         "followers": r.get("followers")}
        for r in results
    ]
    blob = json.dumps(slim)
    dropped = 0
    while len(blob) > _CACHE_VALUE_BUDGET and len(slim) > 1:
        slim.pop()
        dropped += 1
        blob = json.dumps(slim)
    if len(blob) > _CACHE_VALUE_BUDGET:
        # single pathological row still over budget: drop its picture too
        slim = [{k: v for k, v in slim[0].items() if k != "avatar_url"}]
        blob = json.dumps(slim)
        dropped += 1
    if dropped:
        log.warning("cache write trimmed %d row(s) for %s:%s to fit the metadata quota",
                    dropped, platform, query.lower())
    try:
        collection.upsert(
            ids=[f"q:{platform}:{query.lower()}"],
            documents=[f"handle search: {query}"],
            metadatas=[
                {
                    "query": query.lower(),
                    "platform": platform,
                    "results_json": blob,
                    "ts": int(time.time()),
                }
            ],
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("cache write failed (%s)", exc)


def _mapping_put_many(items: list[dict], *, origin: str, query: str = "") -> None:
    """Batch-upsert handles into the growing handle DB (pfp + name + followers).

    Called after every live search with ALL pulled results — not only selections —
    so every pull expands the DB."""
    _, mappings = _collections()
    ids: list[str] = []
    docs: list[str] = []
    metas: list[dict] = []
    for item in items:
        handle = str(item.get("handle") or "").strip().lstrip("@")
        if not handle:
            continue
        platform = item.get("platform") or "x"
        followers = item.get("followers")
        ids.append(f"{platform}:{handle.lower()}")
        docs.append(handle)
        metas.append(
            {
                "handle": handle,
                "platform": platform,
                "display_name": item.get("display_name") or "",
                "avatar_url": item.get("avatar_url") or "",
                "followers": followers
                if isinstance(followers, int) and followers >= 0
                else -1,
                "selected_query": (item.get("selected_query") or query)[:80],
                "origin": origin,
                "ts": int(time.time()),
            }
        )
    if not ids:
        return
    try:
        mappings.upsert(ids=ids, documents=docs, metadatas=metas)
    except Exception as exc:  # noqa: BLE001
        log.warning("mapping write failed (%s)", exc)


def _mapping_put(item: dict) -> None:
    _mapping_put_many(
        [item], origin="selected", query=str(item.get("selected_query") or "")
    )


def _db_handles() -> list[str]:
    """Handles we already know from the main app's DB — prefix match, zero credits."""
    db_path = os.environ.get("HANDLE_SEARCH_DB") or str(LUMI_ROOT / "lumi.db")
    if not db_path or not Path(db_path).exists():
        return []
    try:
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            # Query each table independently: a single UNION aborts entirely if
            # either table is missing (e.g. a slim/partial lumi.db), silently
            # dropping every handle. Missing table -> empty list, no data loss.
            handles: list[str] = []
            for sql in (
                "SELECT handle FROM profiles",
                "SELECT DISTINCT author_handle FROM listening_matches",
            ):
                try:
                    handles += [r[0] for r in con.execute(sql).fetchall() if r and r[0]]
                except sqlite3.Error as exc:
                    log.debug("local db table unavailable (%s): %s", sql, exc)
        finally:
            con.close()
    except Exception as exc:  # noqa: BLE001
        log.warning("local db read failed (%s)", exc)
        return []
    return handles


_session = {"live_queries": 0, "credits_spent": 0}


def _live_enabled() -> bool:
    return os.environ.get("MVP_XPOZ_LIVE", "1").strip().lower() not in ("0", "false", "no")


def _live_budget() -> int:
    """Credit budget for the session (not query count — platforms cost differently)."""
    try:
        return max(0, int(os.environ.get("MVP_XPOZ_BUDGET", str(DEFAULT_LIVE_BUDGET))))
    except ValueError:
        return DEFAULT_LIVE_BUDGET


def _parse_platforms(raw: str | None) -> list[str]:
    """CSV of platform slugs -> validated, deduped, order-preserving list.
    Empty or entirely-unknown input falls back to X so a bad param can never
    switch the search off."""
    picked: list[str] = []
    for part in (raw or "").split(","):
        p = part.strip().lower()
        if p in PLATFORMS and p not in picked:
            picked.append(p)
    return picked or [DEFAULT_PLATFORM]


def _meta_platform(meta: dict) -> str:
    """Platform of a stored row/entry. Rows written before cross-platform support
    carry no platform field — everything then was X."""
    p = str(meta.get("platform") or DEFAULT_PLATFORM).lower()
    return p if p in PLATFORMS else DEFAULT_PLATFORM


def _cache_ttl_minutes() -> int:
    try:
        return max(0, int(os.environ.get("MVP_CACHE_TTL_MINUTES", str(DEFAULT_CACHE_TTL_MINUTES))))
    except ValueError:
        return DEFAULT_CACHE_TTL_MINUTES


def _xpoz_keys() -> list[str]:
    return [k for k in (os.environ.get("XPOZ_API_KEY"), os.environ.get("XPOZ_API_KEY_2")) if k]


async def _xpoz_get(path: str, params: dict) -> list[dict]:
    """GET an Xpoz live endpoint with key rotation on auth/quota failures.

    Returns the `results` list, or [] once every key failed (logged, never raised).
    """
    errors: list[str] = []
    for key in _xpoz_keys():
        try:
            async with httpx.AsyncClient(
                base_url=XPOZ_BASE,
                headers={"Authorization": f"Bearer {key}"},
                timeout=15.0,
            ) as client:
                response = await client.get(path, params=params)
            if response.status_code in (401, 402, 403):
                errors.append(f"key…{key[-4:]} -> {response.status_code} (rotating)")
                continue
            response.raise_for_status()
            return response.json().get("results") or []
        except Exception as exc:  # noqa: BLE001
            errors.append(f"key…{key[-4:]} -> {type(exc).__name__}")
    log.warning("xpoz live search failed (%s): %s", path, "; ".join(errors) or "no keys configured")
    return []


async def _xpoz_user_search(query: str) -> list[dict]:
    """Live X user search (2 credits/query). Rotates keys on auth/quota failures."""
    return await _xpoz_get(
        "/api/data/twitter/users/live",
        {"q": query, "fields": XPOZ_USER_FIELDS},
    )


async def _xpoz_user_search_platform(query: str, platform: str) -> list[dict]:
    """Live user search on any selected platform. X keeps its own single-arg
    path (`_xpoz_user_search` — the seam tests patch); other platforms hit their
    spec'd endpoint with their own param name and field set."""
    if platform == "x":
        return await _xpoz_user_search(query)
    spec = PLATFORMS[platform]
    return await _xpoz_get(
        f"/api/data/{spec['path']}/users/live",
        {spec["param"]: query, "fields": spec["fields"]},
    )


def _normalize_user(platform: str, user: dict) -> dict:
    """Map a platform's raw user object onto the bar's row shape (field names
    differ per platform; missing/None fields stay None — never a fabricated 0)."""
    spec = PLATFORMS[platform]

    def field(key: str) -> Any:
        col = spec.get(key)
        return user.get(col) if col else None

    return _result(
        str(field("handle") or ""),
        field("name"),
        field("avatar"),
        field("followers"),
        "live",
        platform,
    )


def _normalize_query(q: str) -> str:
    return q.strip().lstrip("@")


def _result(handle: str, display_name: str | None, avatar: str | None,
            followers: Any, source: str, platform: str = DEFAULT_PLATFORM) -> dict:
    followers = followers if isinstance(followers, int) and followers >= 0 else None
    return {
        "handle": handle,
        "display_name": display_name or "",
        "avatar_url": avatar or "",
        "followers": followers,
        "source": source,
        "platform": platform,
    }


def _cache_reuse(q_lower: str, plats: list[str]) -> tuple[list[tuple[dict, bool, str]], dict[str, bool]]:
    """Prefix-chain reuse: exact cached queries serve their stored results, narrower
    cached queries filter down, broader queries' results all still match q.
    (Context words never filter here — they only re-rank in `search_handles`, so a
    cached result set is reusable across different sentences for zero extra credits.)
    Only entries on a SELECTED platform are considered — an X cache never answers
    an Instagram query and vice versa.

    Returns ([(result, entry_fresh, platform)...], fresh_exact_by_platform): a FRESH
    exact entry answers its platform's query even when its result list is empty
    (negative cache); a STALE exact entry does not — it triggers a real-time
    re-query instead.
    """
    reused: list[tuple[dict, bool, str]] = []
    fresh_exact: dict[str, bool] = {p: False for p in plats}
    for meta in _cache_get_all(_collections()[0]):
        stored = str(meta.get("query") or "")
        if not stored:
            continue
        plat = _meta_platform(meta)
        if plat not in plats:
            continue
        if not (q_lower.startswith(stored) or stored.startswith(q_lower)):
            continue
        fresh = _entry_fresh(meta)
        if fresh and stored == q_lower:
            fresh_exact[plat] = True
        try:
            stored_results = json.loads(meta.get("results_json") or "[]")
        except (TypeError, ValueError):
            continue
        for item in stored_results:
            handle = str(item.get("handle") or "")
            # Xpoz matches handles CONTAINING the query (q="naval" returns
            # "notnaval" too) — the cache filter mirrors that so a cached paint
            # shows exactly what the live pull showed.
            if q_lower in handle.lower():
                row = dict(item)
                row["platform"] = plat  # legacy result JSON predates platform stamps
                reused.append((row, fresh, plat))
    return reused, fresh_exact


async def search_handles(raw_query: str, context: str = "",
                         platforms: str = "x") -> dict:
    query = _normalize_query(raw_query)
    q_lower = query.lower()
    # The words typed before the @-mention are not ignored: up to 3 of them are
    # kept as context and boost ranking (never sent to Xpoz — Lucene AND would
    # kill the result set and burn credits on an empty answer).
    ctx_words = [w for w in re.split(r"\W+", context.lower()) if w][:3] if context else []
    plats = _parse_platforms(platforms)
    if len(query) < MIN_QUERY_LEN:
        return {
            "query": query,
            "results": [],
            "live": False,
            "refreshed": False,
            "reason": "min_length",
            "context": " ".join(ctx_words),
            "platforms": plats,
        }

    merged: dict[str, dict] = {}
    src_by_key: dict[str, str] = {}
    known_handles: set[str] = set()  # every "platform:handle" already in the handle DB
    db_keys: set[str] = set()  # prefix-matched local-db handles (always saved-half + lead it)
    # Per-platform bookkeeping: memory rows that landed (drives the negative-cache
    # reason), whether a FRESH cached answer covers the platform (only a fresh
    # cache entry may skip THAT platform's live call), staleness, live spend.
    rows_by_p: dict[str, int] = {p: 0 for p in plats}
    fresh_by_p: dict[str, bool] = {p: False for p in plats}
    stale_by_p: dict[str, bool] = {p: False for p in plats}
    live_by_p: dict[str, bool] = {p: False for p in plats}
    reason_by_p: dict[str, str | None] = {p: None for p in plats}

    def _add(item: dict, *, stale: bool = False) -> None:
        handle = str(item.get("handle") or "")
        if not handle:
            return
        plat = str(item.get("platform") or DEFAULT_PLATFORM)
        key = f"{plat}:{handle.lower()}"  # same name on two platforms = two rows
        if key in merged and stale:
            return  # stale data never overwrites fresher data
        merged[key] = item
        src_by_key[key] = item.get("source") or ""
        if plat in rows_by_p:
            rows_by_p[plat] += 1

    # The local db holds X handles only (profiles / listening_matches are X rows),
    # so it feeds the merge only when X is among the selected platforms.
    if DEFAULT_PLATFORM in plats:
        for handle in _db_handles():
            if handle.lower().startswith(q_lower):
                # The handle DB is a HEAD START, not an answer: db rows merge into
                # the results (and paint instantly client-side) but never gate the
                # live search — otherwise "@ateh" would only ever show the one Ateh
                # saved in the db instead of the actual people currently on X. Track
                # membership here: a local-db handle stays in the SAVED half even
                # when a richer cache/live copy of it later overwrites its row, and
                # it leads that half — so @AtehOfficial can never be shuffled out.
                db_keys.add(handle.lower())
                _add(_result(handle, None, None, None, "db", DEFAULT_PLATFORM))

    for meta in _cache_get_all(_collections()[1]):
        handle = str(meta.get("handle") or "")
        plat = _meta_platform(meta)
        # membership is platform-scoped: an X handle known to the db does not mark
        # a same-named Instagram account as already-seen
        known_handles.add(f"{plat}:{handle.lower()}")
        if plat not in plats:
            continue
        if handle.lower().startswith(q_lower):
            followers = meta.get("followers")
            _add(_result(handle, meta.get("display_name"), meta.get("avatar_url"),
                         followers, "cache", plat))

    # Prefix-chain reuse: ka→kar→karp re-uses earlier cached results instead of
    # re-querying Xpoz (credits saved per keystroke level) — but only while the
    # entries are fresh; stale ones trigger the real-time refresh below. Fresh
    # cached results ARE a real recent search, so they (only) may skip the live
    # call — neither the local db nor remembered handles ever do. Reuse is
    # per-platform: an X cache entry never answers an Instagram query.
    cache_items, fresh_exact_by_p = _cache_reuse(q_lower, plats)
    for item, fresh, plat in cache_items:
        _add(_result(item.get("handle") or "", item.get("display_name"),
                     item.get("avatar_url"), item.get("followers"), "cache", plat),
             stale=not fresh)
        if fresh:
            fresh_by_p[plat] = True
        else:
            stale_by_p[plat] = True
    for plat, exact in fresh_exact_by_p.items():
        if exact:
            fresh_by_p[plat] = True  # fresh negative cache: never re-burn the query

    # Live fan-out: each SELECTED platform decides for itself — a fresh cached
    # answer skips live, an unsupported platform stays honest (no provider), and
    # a live call fires only while its own cost still fits the credit budget.
    for plat in plats:
        if fresh_by_p[plat]:
            if rows_by_p[plat] == 0:
                reason_by_p[plat] = "cache_exact"  # fresh negative cache — nothing to show
            continue
        spec = PLATFORMS[plat]
        if not spec.get("live"):
            reason_by_p[plat] = "unsupported"  # e.g. LinkedIn: no provider, db/remembered only
            continue
        if not _live_enabled():
            reason_by_p[plat] = "live_disabled"
            continue
        cost = int(spec.get("credits") or 0)
        if _session.get("credits_spent", 0) + cost > _live_budget():
            reason_by_p[plat] = "budget_exhausted"
            continue
        _session["live_queries"] += 1
        _session["credits_spent"] = _session.get("credits_spent", 0) + cost
        live_by_p[plat] = True
        live_items = [
            u
            for u in (
                _normalize_user(plat, raw)
                for raw in await _xpoz_user_search_platform(query, plat)
            )
            if u["handle"]
        ]
        _cache_put_search(query, live_items, platform=plat)
        for item in live_items:
            _add(item)  # fresh: overwrites any stale cached version of the handle

    live_used = any(live_by_p.values())
    # stale cached results on a platform that just re-queried are replaced by the fresh pull
    refreshed = any(live_by_p[p] and stale_by_p[p] for p in plats)

    # Every pulled handle moves into the handle DB — ALL live results (pfp, name,
    # followers), plus cache results not yet remembered — not just selections.
    # Live pulls always overwrite (fresher data); cache items only write new rows
    # so a re-served handle keeps its original origin label.
    live_persist = [merged[k] for k, s in src_by_key.items() if s == "live"]
    cache_persist = [
        merged[k] for k, s in src_by_key.items()
        if s == "cache" and k not in known_handles
    ]
    if live_persist:
        _mapping_put_many(live_persist, origin="live", query=query)
    if cache_persist:
        _mapping_put_many(cache_persist, origin="cache", query=query)

    results = list(merged.values())

    def _ctx_rank(r: dict) -> int:
        if not ctx_words:
            return 1
        text = f"{r['handle']} {r['display_name']}".lower()
        return 0 if any(w in text for w in ctx_words) else 1

    results.sort(
        key=lambda r: (
            0 if r["handle"].lower() == q_lower else 1,
            # main-app db handles (e.g. @AtehOfficial) lead their group so the one
            # account you own is never shuffled out of the top by strangers
            0 if r["handle"].lower() in db_keys else 1,
            _ctx_rank(r),
            0 if r["followers"] is not None else 1,
            -(r["followers"] or 0),
            r["handle"].lower(),
        )
    )

    # Half-and-half mix by WHERE each handle came from on THIS search:
    #   saved half — served from memory (local db / remembered / past-search cache)
    #                or owned by the main app (db_keys, even if a live pull
    #                re-surfaced them). The bar already knows these.
    #   live half  — returned by the fresh Xpoz pull just now and not a main-app
    #                handle: what X actually has right now, never gate-kept.
    # Up to MIX_HALF from each; a short side hands its leftover slots to the other
    # so the list still fills to MIX_TOTAL. The exact-typed handle leads the list.
    def _is_saved(r: dict) -> bool:
        return r["source"] != "live" or r["handle"].lower() in db_keys

    saved = [r for r in results if _is_saved(r)]
    live = [r for r in results if not _is_saved(r)]
    k = min(len(saved), MIX_HALF)
    o = min(len(live), MIX_HALF)
    deficit = MIX_TOTAL - (k + o)
    if deficit > 0:
        extra = min(deficit, len(saved) - k)
        k += extra
        deficit -= extra
        o += min(deficit, len(live) - o)
    mixed = saved[:k] + live[:o]
    for i, r in enumerate(mixed):
        if r["handle"].lower() == q_lower:
            mixed.insert(0, mixed.pop(i))
            break

    top_reason = next((reason_by_p[p] for p in plats if reason_by_p[p]), None)
    return {
        "query": query,
        "results": mixed[:MIX_TOTAL],
        "live": live_used,
        "refreshed": refreshed,
        "reason": top_reason,
        "context": " ".join(ctx_words),
        "platforms": plats,
        "platform_reasons": {p: reason_by_p[p] for p in plats},
        "live_queries_this_session": _session["live_queries"],
        "credits_spent_this_session": _session.get("credits_spent", 0),
    }


class SelectHandle(BaseModel):
    handle: str = Field(min_length=1, max_length=64)
    platform: str = "x"
    display_name: str = ""
    avatar_url: str = ""
    followers: int | None = None
    selected_query: str = ""


app = FastAPI(title="Lumi @-handle bar MVP")


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/handles/search")
async def api_search(q: str = "", context: str = "", platforms: str = "x") -> dict:
    return await search_handles(q, context=context, platforms=platforms)


@app.get("/api/handles/saved")
async def api_saved(platforms: str = "x") -> dict:
    """Every saved handle (local db + remembered store) for the instant suggest layer.

    The bar keeps this snapshot client-side and prefix-filters it on each keystroke
    — 0 ms, no request, no credits — then the debounced full search refines the same
    dropdown. The snapshot is refreshed after every full search. `platforms` filters
    the snapshot to the selected platforms (the local db is X-only)."""
    plats = _parse_platforms(platforms)
    items: list[dict] = []
    seen: set[str] = set()
    if DEFAULT_PLATFORM in plats:
        for handle in _db_handles():
            key = f"{DEFAULT_PLATFORM}:{handle.lower().lstrip('@')}"
            if not handle or key in seen:
                continue
            seen.add(key)
            items.append(_result(handle, None, None, None, "db", DEFAULT_PLATFORM))
    for meta in _cache_get_all(_collections()[1]):
        handle = str(meta.get("handle") or "").strip().lstrip("@")
        plat = _meta_platform(meta)
        if plat not in plats:
            continue
        key = f"{plat}:{handle.lower()}"
        if not handle or key in seen:
            continue
        seen.add(key)
        items.append(_result(handle, meta.get("display_name"), meta.get("avatar_url"),
                             meta.get("followers"), "cache", plat))
    items.sort(
        key=lambda r: (
            0 if r["followers"] is not None else 1,
            -(r["followers"] or 0),
            r["handle"].lower(),
        )
    )
    return {"results": items[:500], "count": len(items)}


@app.post("/api/handles/select")
async def api_select(item: SelectHandle) -> dict:
    _mapping_put(item.model_dump())
    return {"remembered": True, "handle": item.handle.lstrip("@").lower()}


@app.get("/api/handles/stats")
async def api_stats() -> JSONResponse:
    cache, mappings = _collections()

    def _collection_stats(collection: Any) -> tuple[int, dict[str, int]]:
        # paged read — the raw get() stops at the 300-row Get quota and would
        # undercount (and mislabel origins) once the collection grows past it
        metadatas = _cache_get_all(collection)
        origins: dict[str, int] = {}
        for meta in metadatas:
            origin = str(meta.get("origin") or "unknown")
            origins[origin] = origins.get(origin, 0) + 1
        return len(metadatas), origins

    cached_searches, _ = _collection_stats(cache)
    remembered_handles, origins = _collection_stats(mappings)

    # "saved handles" = every distinct handle we already know, from either source
    # (local lumi.db + the remembered Chroma store), deduped case-insensitively.
    db_set = {h.lower().lstrip("@") for h in _db_handles()}
    remembered_set = {
        str(m.get("handle") or "").lower().lstrip("@")
        for m in _cache_get_all(mappings)
        if m.get("handle")
    }
    saved_handles = len(db_set | remembered_set)

    return JSONResponse(
        {
            "live_queries_this_session": _session["live_queries"],
            "credits_spent_this_session": _session.get("credits_spent", 0),
            "live_budget": _live_budget(),  # in credits
            "live_enabled": _live_enabled(),
            "cache_ttl_minutes": _cache_ttl_minutes(),
            "saved_handles": saved_handles,
            "known_db_handles": len(db_set),
            "remembered_handles": remembered_handles,
            "remembered_by_origin": origins,
            "cached_searches": cached_searches,
            # what the bar's platform selector renders from (label + live ability +
            # per-query credit cost — the UI can show "12 credits" before you pick it)
            "available_platforms": [
                {
                    "id": p,
                    "label": spec.get("label") or p,
                    "live": bool(spec.get("live")),
                    "credits": int(spec.get("credits") or 0),
                }
                for p, spec in PLATFORMS.items()
            ],
        }
    )
