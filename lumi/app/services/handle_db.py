"""Shared handle DB — every user-search the main app runs feeds it.

The @-handle bar MVP owns the store: Chroma Cloud (credentials from the
MVP_CHROMA_* names in `.env`, database `Onscript`), collection
`handle_mappings` — every handle ever pulled or selected lands there with
picture, display name and follower count, keyed `x:<handle>`.

This module is the MAIN app's side of that same store. Chronic Online scans
and niche keyword searches persist every user they touch (the tracked
accounts, the authors of every returned post), so the handle DB keeps
expanding with every search anywhere in the system — not just the bar.

Rules (the store is a HELP layered on, never a dependency):
- add-if-absent: never overwrites fresher rows or their origin labels —
  the MVP's live pulls stay authoritative (they carry real pfp/followers).
- never raises, never blocks the search path: every failure logs and returns 0.
- no MVP_CHROMA_* config (e.g. prod) → silent no-op, zero cost.
- missing data stays missing: name/avatar/followers are only stored when a
  response actually carried them (followers absent → -1 sentinel, which the
  MVP reads back as NULL — never fabricated).
- bounded enrichment: handles the store has never seen may be completed with
  the verified Xpoz user search (2 credits each, EXACT username match only —
  a fuzzy top-hit is not this person, so their picture is never stored),
  capped by HANDLE_DB_ENRICH_LIMIT per call (default 6; 0 disables).
  Post authors from keyword searches are saved handle-only: enriching an
  unbounded author list would burn dozens of credits, and the bar falls back
  to unavatar for their picture anyway.
"""

import logging
import os
import time
from pathlib import Path
from typing import Any

import httpx

log = logging.getLogger(__name__)

LUMI_ROOT = Path(__file__).resolve().parents[2]  # app/services -> lumi/
XPOZ_BASE = "https://api.xpoz.ai"
XPOZ_USER_FIELDS = "username,name,profileImageUrl,followersCount"
DEFAULT_ENRICH_LIMIT = 6  # new scanned handles enriched (2 credits each) per call

_collection_cache: Any = None
_collection_resolved = False


def _load_dotenv() -> None:
    """Minimal .env reader for names pydantic-settings ignores (MVP_CHROMA_*).

    Settings only populates its declared fields, so these never reach
    os.environ otherwise. Existing values (Railway) always win; values are
    never logged."""
    try:
        lines = (LUMI_ROOT / ".env").read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv()


def _collection() -> Any:
    """The MVP's `handle_mappings` collection, or None when unavailable."""
    global _collection_cache, _collection_resolved
    if _collection_resolved:
        return _collection_cache
    _collection_resolved = True
    api_key = os.environ.get("MVP_CHROMA_API_KEY")
    tenant = os.environ.get("MVP_CHROMA_TENANT")
    database = os.environ.get("MVP_CHROMA_DATABASE")
    if not (api_key and tenant and database):
        log.debug("handle_db: MVP_CHROMA_* not configured — writes skipped")
        _collection_cache = None
        return None
    try:
        import chromadb

        client = chromadb.CloudClient(api_key=api_key, tenant=tenant, database=database)
        _collection_cache = client.get_or_create_collection("handle_mappings")
        log.info("handle_db: connected to handle_mappings (database=%s)", database)
    except Exception as exc:  # noqa: BLE001 — the store is an enrichment, never a dependency
        log.warning("handle_db: Chroma unavailable (%s) — writes skipped", exc)
        _collection_cache = None
    return _collection_cache


def _reset_for_tests() -> None:
    """Drop the cached collection handle so env changes apply (tests only)."""
    global _collection_cache, _collection_resolved
    _collection_cache = None
    _collection_resolved = False


def _mapping_id(platform: str, handle: str) -> str:
    """MVP-compatible row id: `x:karpathy` (lowercased handle)."""
    return f"{platform}:{handle.lower()}"


def _existing_ids(collection: Any, ids: list[str]) -> set[str]:
    """Ids already in the store. A failed check means 'unknown to us' is
    unknowable — callers then write nothing rather than risk clobbering."""
    try:
        return set(collection.get(ids=ids, include=[]).get("ids") or [])
    except Exception as exc:
        log.warning("handle_db: existence check failed (%s)", exc)
        raise


def remember(items: list[dict], *, origin: str, query: str = "") -> int:
    """Add handles to the shared DB; returns rows actually written.

    Only rows the store has never seen are written (same rule as the MVP's
    cache path): existing rows keep their data and origin label."""
    try:
        return _remember(items, origin=origin, query=query)
    except Exception as exc:  # noqa: BLE001 — never break a search over the DB
        log.warning("handle_db: write skipped (%s)", exc)
        return 0


def _remember(items: list[dict], *, origin: str, query: str) -> int:
    collection = _collection()
    if collection is None or not items:
        return 0

    # id -> (document, metadata), exactly the MVP's row shape
    rows: dict[str, tuple[str, dict]] = {}
    for item in items:
        handle = str(item.get("handle") or "").strip().lstrip("@")
        if not handle:
            continue
        platform = str(item.get("platform") or "x")
        followers = item.get("followers")
        doc_id = _mapping_id(platform, handle)
        if doc_id in rows:
            continue
        rows[doc_id] = (
            handle,
            {
                "handle": handle,
                "platform": platform,
                "display_name": item.get("display_name") or "",
                "avatar_url": item.get("avatar_url") or "",
                "followers": followers
                if isinstance(followers, int) and followers >= 0
                else -1,  # -1 sentinel == NULL (never a fabricated 0)
                "selected_query": (item.get("selected_query") or query)[:80],
                "origin": origin,
                "ts": int(time.time()),
            },
        )
    if not rows:
        return 0

    existing = _existing_ids(collection, list(rows))
    new_ids = [doc_id for doc_id in rows if doc_id not in existing]
    if not new_ids:
        return 0

    collection.upsert(
        ids=new_ids,
        documents=[rows[i][0] for i in new_ids],
        metadatas=[rows[i][1] for i in new_ids],
    )
    log.debug("handle_db: +%d handles (origin=%s)", len(new_ids), origin)
    return len(new_ids)


def _enrich_limit() -> int:
    try:
        return max(0, int(os.environ.get("HANDLE_DB_ENRICH_LIMIT", str(DEFAULT_ENRICH_LIMIT))))
    except ValueError:
        return DEFAULT_ENRICH_LIMIT


def _xpoz_keys() -> list[str]:
    return [k for k in (os.environ.get("XPOZ_API_KEY"), os.environ.get("XPOZ_API_KEY_2")) if k]


async def _user_profile(handle: str) -> dict | None:
    """Bounded enrichment: the verified Xpoz user search (2 credits).

    Returns profile data ONLY for the exact username match (case-insensitive)
    — a fuzzy top-hit is a different person and their picture/follower count
    must never be stored under this handle. None = save handle-only."""
    target = handle.lower()
    for key in _xpoz_keys():
        try:
            async with httpx.AsyncClient(
                base_url=XPOZ_BASE,
                headers={"Authorization": f"Bearer {key}"},
                timeout=15.0,
            ) as client:
                response = await client.get(
                    "/api/data/twitter/users/live",
                    params={"q": handle, "fields": XPOZ_USER_FIELDS},
                )
            if response.status_code in (401, 402, 403):
                continue  # rotate to the next key
            response.raise_for_status()
            results = response.json().get("results") or []
        except Exception as exc:  # noqa: BLE001
            log.debug("handle_db: enrichment lookup for @%s failed (%s)", handle, type(exc).__name__)
            continue
        for user in results:
            if str(user.get("username") or "").strip().lower() == target:
                followers = user.get("followersCount")
                return {
                    "handle": str(user.get("username") or handle),
                    "display_name": user.get("name") or "",
                    "avatar_url": user.get("profileImageUrl") or "",
                    "followers": followers
                    if isinstance(followers, int) and followers >= 0
                    else None,
                }
        return None  # search succeeded, no exact match — don't spend another query
    return None


async def remember_scanned(
    handles: list[str], *, origin: str, query: str = ""
) -> int:
    """Persist the accounts a search just listened to (Chronic Online scans,
    niche tracked lists) — with picture/name/followers for handles the store
    has never seen (bounded enrichment, see module docstring).

    Never raises; returns rows written."""
    try:
        return await _remember_scanned(handles, origin=origin, query=query)
    except Exception as exc:  # noqa: BLE001 — never break a scan over the DB
        log.warning("handle_db: scanned-handle save skipped (%s)", exc)
        return 0


async def _remember_scanned(handles: list[str], *, origin: str, query: str) -> int:
    collection = _collection()
    if collection is None:
        return 0

    clean: list[str] = []
    seen: set[str] = set()
    for raw in handles:
        handle = str(raw or "").strip().lstrip("@")
        if handle and handle.lower() not in seen:
            seen.add(handle.lower())
            clean.append(handle)
    if not clean:
        return 0

    ids = [_mapping_id("x", h) for h in clean]
    try:
        existing = _existing_ids(collection, ids)
        check_ok = True
    except Exception:  # noqa: BLE001 — unknown is unknowable: save, don't enrich
        existing, check_ok = set(), False

    limit = _enrich_limit()
    unknown = [h for h, i in zip(clean, ids, strict=True) if i not in existing]
    to_enrich = set(unknown[:limit]) if check_ok else set()

    items: list[dict] = []
    for handle in clean:
        item: dict[str, Any] = {"handle": handle}
        if handle in to_enrich:
            profile = await _user_profile(handle)
            if profile:
                item.update(profile)
        items.append(item)
    return remember(items, origin=origin, query=query)
