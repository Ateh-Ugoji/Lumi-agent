from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Protocol, runtime_checkable

Source = Literal["db", "cache", "live"]

# Reasons a platform did not answer from a live call. ``None`` means nothing to explain.
REASON_MIN_LENGTH = "min_length"
REASON_CACHE_EXACT = "cache_exact"
REASON_UNSUPPORTED = "unsupported"
REASON_LIVE_DISABLED = "live_disabled"
REASON_BUDGET = "budget_exhausted"
REASON_UNAVAILABLE = "provider_unavailable"
REASON_RATE_LIMITED = "rate_limited"
REASON_AUTH = "auth_error"


@dataclass(frozen=True, slots=True)
class HandleRow:
    """One account in the dropdown. ``followers`` is ``None`` when unknown, never 0."""

    handle: str
    platform: str
    display_name: str = ""
    avatar_url: str = ""
    followers: int | None = None
    source: Source = "cache"

    @property
    def key(self) -> str:
        return f"{self.platform}:{self.handle.lower()}"


@dataclass(frozen=True, slots=True)
class CacheEntry:
    """A past search for one platform and one normalized query."""

    platform: str
    query: str  # normalized: no "@", lowercase
    fetched_at: datetime
    rows: tuple[HandleRow, ...] = ()


@dataclass(frozen=True, slots=True)
class HandleSearchResult:
    query: str
    results: tuple[HandleRow, ...]
    live: bool
    refreshed: bool
    reason: str | None
    context: str
    platforms: tuple[str, ...]
    platform_reasons: Mapping[str, str | None] = field(default_factory=dict)


@runtime_checkable
class HandleStore(Protocol):
    """Persistence behind the search. The Django implementation uses Postgres tables."""

    async def profile_handles(self, platform: str, prefix: str) -> list[str]:
        """Handles of profiles already in Lumi that start with ``prefix``. Costs nothing."""
        ...

    async def remembered(self, platform: str, prefix: str) -> list[HandleRow]:
        """Every handle ever pulled or selected on ``platform`` that starts with ``prefix``."""
        ...

    async def known_keys(self, platform: str, handles: list[str]) -> set[str]:
        """Which of ``handles`` are already remembered, as ``platform:handle`` lowercase keys."""
        ...

    async def related_entries(self, platform: str, query: str) -> list[CacheEntry]:
        """Cached searches whose query starts with ``query`` or is a prefix of it."""
        ...

    async def put_entry(self, entry: CacheEntry) -> None:
        """Save or replace the cache entry of (platform, query)."""
        ...

    async def remember_live(self, rows: list[HandleRow]) -> None:
        """Upsert rows from a fresh pull, overwriting older data."""
        ...

    async def remember_new(self, rows: list[HandleRow]) -> None:
        """Insert rows that are not remembered yet. Existing rows keep their data."""
        ...


@runtime_checkable
class HandleLive(Protocol):
    """The paid lookup. It raises the typed errors of ``apps.connections.errors``."""

    def supports(self, platform: str) -> bool: ...

    async def search(self, platform: str, query: str) -> list[HandleRow]: ...
