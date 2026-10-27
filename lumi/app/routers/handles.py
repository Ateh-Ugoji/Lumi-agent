"""@-handle search on the main app's origin — a thin shim over the handle-search MVP.

The MVP core (`mvp/handle_search/server.py`) remains the single source of truth for
the cache-first, credit-aware search (local db head-start -> remembered -> 60-min
cache with prefix-chain reuse -> budget-guarded Xpoz live, half-and-half mix). This
router exposes the same four operations under `/handles/*` so the main frontend
talks to ONE API base (no second hardcoded origin, no CORS dependency on the
standalone MVP at :8010, and the endpoints exist wherever the backend runs).

Delegation, not duplication: the route handlers call the MVP's own endpoint
functions (`api_search`, `api_saved`, `api_select`, `api_stats`) directly. The
standalone MVP keeps working unchanged at :8010.

Credit note: a live Xpoz query fires per SELECTED platform only when that platform
has no fresh cached answer (X/Reddit 2, TikTok 5, Instagram 12 credits; LinkedIn
has no provider and never spends); `MVP_XPOZ_LIVE=0` disables live entirely and
`MVP_XPOZ_BUDGET` caps live CREDITS per server process.
"""

from fastapi import APIRouter

from mvp.handle_search import server as handle_core

router = APIRouter(prefix="/handles", tags=["handles"])


@router.get("/search")
async def search_handles(q: str = "", context: str = "", platforms: str = "x") -> dict:
    """Search handles across the SELECTED platforms (`platforms` CSV, default "x":
    x | instagram | tiktok | reddit | linkedin — linkedin has no live provider and
    answers from db/remembered only). `context` = up to 3 words typed before the @
    (re-ranks results, never sent to Xpoz). Returns results with `source` per
    handle (db | cache | live) and `platform`, plus `live`/`refreshed`/`reason`/
    `platform_reasons` bookkeeping."""
    return await handle_core.api_search(q=q, context=context, platforms=platforms)


@router.get("/saved")
async def list_saved_handles(platforms: str = "x") -> dict:
    """Instant-suggest snapshot (local db + remembered store), deduped, sorted,
    filtered to the selected `platforms`. The composer prefix-filters this
    client-side per keystroke: 0 ms, 0 credits."""
    return await handle_core.api_saved(platforms=platforms)


@router.post("/select")
async def select_handle(item: handle_core.SelectHandle) -> dict:
    """Remember a picked handle (cross-platform handle-mapping seed)."""
    return await handle_core.api_select(item)


@router.get("/stats")
async def get_handle_stats():
    """Credit meter + saved-handle counts + cache TTL (JSONResponse passthrough)."""
    return await handle_core.api_stats()
