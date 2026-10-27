"""Handle search service. Pure logic over a ``HandleStore`` and a ``HandleLive``.

Layers, cheapest first:

1. profile handles already in Lumi (free, lead their half of the list)
2. remembered handles (free)
3. cached searches, reused along the prefix chain ``ka`` -> ``kar`` -> ``karp``
4. a live lookup per platform, only when no FRESH cached answer covers that platform

Layers 1 and 2 are a head start and never replace the live call. Only a fresh cache entry
(a real recent search, an empty one included) may skip it. A failed live call is never cached,
so one outage cannot hide a platform for a whole TTL.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import datetime, timedelta

from ..errors import (
    BudgetExceeded,
    LiveDisabled,
    ProviderAuthError,
    ProviderUnavailable,
    RateLimited,
    UnsupportedPlatform,
)
from ..providers.base import utcnow
from .ranking import (
    MIN_QUERY_LEN,
    context_words,
    mix,
    normalize_query,
    parse_platforms,
    rank,
)
from .types import (
    REASON_AUTH,
    REASON_BUDGET,
    REASON_CACHE_EXACT,
    REASON_LIVE_DISABLED,
    REASON_MIN_LENGTH,
    REASON_RATE_LIMITED,
    REASON_UNAVAILABLE,
    REASON_UNSUPPORTED,
    CacheEntry,
    HandleLive,
    HandleRow,
    HandleSearchResult,
    HandleStore,
)

_ERROR_REASONS: tuple[tuple[type[Exception], str], ...] = (
    (LiveDisabled, REASON_LIVE_DISABLED),
    (BudgetExceeded, REASON_BUDGET),
    (UnsupportedPlatform, REASON_UNSUPPORTED),
    (RateLimited, REASON_RATE_LIMITED),
    (ProviderAuthError, REASON_AUTH),
    (ProviderUnavailable, REASON_UNAVAILABLE),
)


def _reason_for(exc: Exception) -> str | None:
    for kind, reason in _ERROR_REASONS:
        if isinstance(exc, kind):
            return reason
    return None


class HandleSearch:
    def __init__(
        self,
        store: HandleStore,
        live: HandleLive,
        *,
        ttl_minutes: int,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._store = store
        self._live = live
        self._ttl = timedelta(minutes=max(0, ttl_minutes))
        self._clock = clock

    def _fresh(self, entry: CacheEntry) -> bool:
        return self._clock() - entry.fetched_at < self._ttl

    async def search(
        self,
        raw_query: str,
        *,
        platforms: str | Iterable[str] | None = "x",
        context: str = "",
    ) -> HandleSearchResult:
        query = normalize_query(raw_query)
        q = query.lower()
        plats = parse_platforms(platforms)
        ctx = context_words(context)
        if len(query) < MIN_QUERY_LEN:
            return HandleSearchResult(
                query=query,
                results=(),
                live=False,
                refreshed=False,
                reason=REASON_MIN_LENGTH,
                context=" ".join(ctx),
                platforms=tuple(plats),
            )

        merged: dict[str, HandleRow] = {}
        db_keys: set[str] = set()
        rows_by_p = {p: 0 for p in plats}
        fresh_by_p = {p: False for p in plats}
        stale_by_p = {p: False for p in plats}
        live_by_p = {p: False for p in plats}
        reason_by_p: dict[str, str | None] = {p: None for p in plats}

        def add(row: HandleRow, *, stale: bool = False) -> None:
            if not row.handle:
                return
            if row.key in merged and stale:
                return  # stale data never overwrites fresher data
            merged[row.key] = row
            if row.platform in rows_by_p:
                rows_by_p[row.platform] += 1

        for plat in plats:
            for handle in await self._store.profile_handles(plat, q):
                if handle.lower().startswith(q):
                    row = HandleRow(handle, plat, source="db")
                    db_keys.add(row.key)
                    add(row)
            for row in await self._store.remembered(plat, q):
                if row.handle.lower().startswith(q):
                    add(
                        HandleRow(
                            row.handle,
                            plat,
                            row.display_name,
                            row.avatar_url,
                            row.followers,
                            "cache",
                        )
                    )
            for entry in await self._store.related_entries(plat, q):
                fresh = self._fresh(entry)
                if fresh and entry.query == q:
                    fresh_by_p[plat] = True  # fresh negative cache included
                if not (q.startswith(entry.query) or entry.query.startswith(q)):
                    continue
                for row in entry.rows:
                    # The provider matches handles that CONTAIN the query, so the cache does too.
                    if q in row.handle.lower():
                        add(
                            HandleRow(
                                row.handle,
                                plat,
                                row.display_name,
                                row.avatar_url,
                                row.followers,
                                "cache",
                            ),
                            stale=not fresh,
                        )
                        if fresh:
                            fresh_by_p[plat] = True
                        else:
                            stale_by_p[plat] = True

        for plat in plats:
            if fresh_by_p[plat]:
                if rows_by_p[plat] == 0:
                    reason_by_p[plat] = REASON_CACHE_EXACT
                continue
            if not self._live.supports(plat):
                reason_by_p[plat] = REASON_UNSUPPORTED
                continue
            try:
                found = await self._live.search(plat, query)
            except Exception as exc:
                reason = _reason_for(exc)
                if reason is None:
                    raise
                reason_by_p[plat] = reason
                continue
            live_by_p[plat] = True
            live_rows = [
                HandleRow(
                    r.handle, plat, r.display_name, r.avatar_url, r.followers, "live"
                )
                for r in found
                if r.handle
            ]
            await self._store.put_entry(
                CacheEntry(plat, q, self._clock(), tuple(live_rows))
            )
            for row in live_rows:
                add(row)

        live_rows_all = [r for r in merged.values() if r.source == "live"]
        if live_rows_all:
            await self._store.remember_live(live_rows_all)
        cache_rows = [r for r in merged.values() if r.source == "cache"]
        if cache_rows:
            known: set[str] = set()
            for plat in plats:
                subset = [r for r in cache_rows if r.platform == plat]
                if subset:
                    known |= await self._store.known_keys(
                        plat, [r.handle for r in subset]
                    )
            fresh_cache = [r for r in cache_rows if r.key not in known]
            if fresh_cache:
                await self._store.remember_new(fresh_cache)

        ranked = rank(merged.values(), q, db_keys=db_keys, ctx_words=ctx)
        mixed = mix(ranked, q, db_keys=db_keys)
        return HandleSearchResult(
            query=query,
            results=tuple(mixed),
            live=any(live_by_p.values()),
            refreshed=any(live_by_p[p] and stale_by_p[p] for p in plats),
            reason=next((reason_by_p[p] for p in plats if reason_by_p[p]), None),
            context=" ".join(ctx),
            platforms=tuple(plats),
            platform_reasons=dict(reason_by_p),
        )
