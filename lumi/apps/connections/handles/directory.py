"""The handle directory: what a scan learns about accounts, and the pictures it can reuse.

This replaces ``legacy/app/services/handle_db.py``. A scan (Chronic Online, a niche search) calls
``remember_scanned`` with the accounts it listened to and ``remember`` with the authors it met.
The render path calls ``pictures`` to find a face for an author.

Rules, as in the legacy module:

* The directory is a help layered on a search, never a dependency of it. Nothing here raises.
* Add-if-absent: a handle that is already stored keeps what it has, a picture included.
  Replacing an old picture is a different operation and lives in ``apps.profiles``.
* Missing data stays missing. A name, a picture or a follower count is stored only when a
  response carried it.
* Enrichment is bounded. A handle the store has never seen may be completed with one paid
  user search, and only up to ``enrich_limit`` per call. Only an EXACT username match counts:
  the top hit of a fuzzy search is another person, and their picture is never stored here.
* If the store cannot be read, nothing is saved and no credit is spent.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Protocol

from .types import HandleRow

log = logging.getLogger(__name__)

DEFAULT_PLATFORM = "x"


@dataclass(frozen=True, slots=True)
class Picture:
    """What a render needs for an author. ``avatar_url`` is never empty."""

    avatar_url: str
    display_name: str = ""
    followers: int | None = None


class DirectoryStore(Protocol):
    async def known_keys(self, platform: str, handles: list[str]) -> set[str]: ...

    async def remember_rows(self, rows: list[HandleRow], origin: str) -> None: ...

    async def pictures(self, platform: str, handles: list[str]) -> list[HandleRow]: ...


class ExactUserLookup(Protocol):
    """The paid lookup. ``None`` when no account has exactly this username."""

    async def exact(self, platform: str, handle: str) -> HandleRow | None: ...


def _clean(handles: Iterable[str]) -> list[str]:
    """Handles without ``@`` or blanks, one per case-insensitive name, in order."""
    seen: set[str] = set()
    out: list[str] = []
    for raw in handles:
        handle = str(raw or "").strip().lstrip("@")
        if handle and handle.lower() not in seen:
            seen.add(handle.lower())
            out.append(handle)
    return out


class HandleDirectory:
    def __init__(
        self,
        store: DirectoryStore,
        lookup: ExactUserLookup | None = None,
        *,
        enrich_limit: int = 0,
    ) -> None:
        self._store = store
        self._lookup = lookup
        self._limit = max(0, enrich_limit)

    async def remember(
        self,
        handles: Sequence[str | HandleRow],
        *,
        origin: str,
        platform: str = DEFAULT_PLATFORM,
    ) -> int:
        """Save accounts that are not stored yet, with no paid lookup. Returns how many are new."""
        try:
            rows = [
                h
                if isinstance(h, HandleRow)
                else HandleRow(handle=h.strip().lstrip("@"), platform=platform)
                for h in handles
                if (h.handle if isinstance(h, HandleRow) else str(h or "").strip())
            ]
            return await self._save(rows, origin)
        except Exception as exc:  # noqa: BLE001 - a scan must never fail over the directory
            log.warning("handle directory: save skipped (%s)", type(exc).__name__)
            return 0

    async def remember_scanned(
        self,
        handles: Sequence[str],
        *,
        origin: str,
        platform: str = DEFAULT_PLATFORM,
    ) -> int:
        """Save the accounts a scan listened to. New ones are completed, up to the limit."""
        try:
            return await self._remember_scanned(list(handles), origin, platform)
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "handle directory: scanned save skipped (%s)", type(exc).__name__
            )
            return 0

    async def pictures(
        self, handles: Sequence[str], *, platform: str = DEFAULT_PLATFORM
    ) -> dict[str, Picture]:
        """``{lowercase handle: Picture}`` for stored accounts that have a picture."""
        try:
            wanted = _clean(handles)
            if not wanted:
                return {}
            rows = await self._store.pictures(platform, wanted)
        except Exception as exc:  # noqa: BLE001 - a render must never fail over the directory
            log.debug("handle directory: lookup skipped (%s)", type(exc).__name__)
            return {}
        return {
            r.handle.lower(): Picture(r.avatar_url, r.display_name, r.followers)
            for r in rows
            if r.avatar_url
        }

    async def _remember_scanned(
        self, handles: list[str], origin: str, platform: str
    ) -> int:
        clean = _clean(handles)
        if not clean:
            return 0
        known = await self._store.known_keys(platform, clean)  # raises: store down
        unknown = [h for h in clean if f"{platform}:{h.lower()}" not in known]
        to_enrich = set(unknown[: self._limit]) if self._lookup else set()
        rows: list[HandleRow] = []
        for handle in clean:
            row = HandleRow(handle=handle, platform=platform)
            if handle in to_enrich:
                row = await self._complete(row)
            rows.append(row)
        return await self._save(rows, origin)

    async def _complete(self, row: HandleRow) -> HandleRow:
        assert self._lookup is not None
        try:
            found = await self._lookup.exact(row.platform, row.handle)
        except Exception as exc:  # noqa: BLE001 - budget, auth, outage: save the handle alone
            log.debug(
                "handle directory: completing @%s failed (%s)",
                row.handle,
                type(exc).__name__,
            )
            return row
        if found is None or found.handle.lower() != row.handle.lower():
            return row
        return HandleRow(
            handle=row.handle,
            platform=row.platform,
            display_name=found.display_name,
            avatar_url=found.avatar_url,
            followers=found.followers,
            source="live",
        )

    async def _save(self, rows: list[HandleRow], origin: str) -> int:
        if not rows:
            return 0
        by_platform: dict[str, list[str]] = {}
        for row in rows:
            by_platform.setdefault(row.platform, []).append(row.handle)
        known: set[str] = set()
        for platform, names in by_platform.items():
            known |= await self._store.known_keys(platform, names)
        await self._store.remember_rows(rows, origin)
        fresh = {r.key for r in rows} - known
        return len(fresh)
