from __future__ import annotations

from datetime import UTC, datetime, timedelta

from apps.connections.handles.types import CacheEntry, HandleRow

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)


class Clock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kw: float) -> None:
        self.now += timedelta(**kw)


class MemoryHandleStore:
    """In-memory ``HandleStore``. The Postgres one is ARCHITECT's."""

    def __init__(self) -> None:
        self.profiles: dict[str, list[str]] = {}
        self.rows: dict[str, HandleRow] = {}
        self.entries: dict[tuple[str, str], CacheEntry] = {}
        self.live_writes: list[list[HandleRow]] = []
        self.new_writes: list[list[HandleRow]] = []

    async def profile_handles(self, platform, prefix):
        return [
            h for h in self.profiles.get(platform, []) if h.lower().startswith(prefix)
        ]

    async def remembered(self, platform, prefix):
        return [
            r
            for r in self.rows.values()
            if r.platform == platform and r.handle.lower().startswith(prefix)
        ]

    async def known_keys(self, platform, handles):
        keys = {f"{platform}:{h.lower()}" for h in handles}
        return keys & set(self.rows)

    async def related_entries(self, platform, query):
        return [
            e
            for (p, q), e in self.entries.items()
            if p == platform and (q.startswith(query) or query.startswith(q))
        ]

    async def put_entry(self, entry):
        self.entries[(entry.platform, entry.query)] = entry

    async def remember_live(self, rows):
        self.live_writes.append(list(rows))
        for r in rows:
            self.rows[r.key] = r

    async def remember_new(self, rows):
        self.new_writes.append(list(rows))
        for r in rows:
            self.rows.setdefault(r.key, r)


class ScriptedLive:
    """``HandleLive`` that answers from a dict and counts the paid calls."""

    def __init__(
        self, answers=None, supported=("x", "instagram", "tiktok", "reddit"), error=None
    ):
        self.answers = answers or {}
        self.supported = set(supported)
        self.error = error
        self.calls: list[tuple[str, str]] = []

    def supports(self, platform):
        return platform in self.supported

    async def search(self, platform, query):
        self.calls.append((platform, query))
        if self.error is not None:
            raise self.error
        return list(self.answers.get(platform, []))


def row(handle, platform="x", followers=None, name="", source="live"):
    return HandleRow(handle, platform, name, "", followers, source)
