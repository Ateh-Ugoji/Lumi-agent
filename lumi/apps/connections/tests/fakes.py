"""Test doubles: a recording MockTransport and an in-memory OAuth state store."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import httpx

from apps.connections.oauth import OAuthStateRecord

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class Recorder:
    """An ``httpx.MockTransport`` that remembers every request it receives."""

    def __init__(self, handler: Callable[[httpx.Request], httpx.Response]) -> None:
        self.requests: list[httpx.Request] = []
        self._handler = handler
        self.transport = httpx.MockTransport(self._record)

    def _record(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self._handler(request)

    @property
    def hosts(self) -> list[str]:
        return [r.url.host for r in self.requests]


def routes(
    table: dict[
        tuple[str, str], httpx.Response | Callable[[httpx.Request], httpx.Response]
    ],
):
    """Route by (method, path). An unexpected request fails the test loudly."""

    def handler(request: httpx.Request) -> httpx.Response:
        entry = table.get((request.method, request.url.path))
        if entry is None:
            raise AssertionError(
                f"unexpected request {request.method} {request.url.host}{request.url.path}"
            )
        return entry(request) if callable(entry) else entry

    return handler


def json_response(
    name: str, status: int = 200, headers: dict | None = None
) -> httpx.Response:
    return httpx.Response(status, json=fixture(name), headers=headers)


class MemoryStateStore:
    def __init__(self) -> None:
        self.records: dict[str, OAuthStateRecord] = {}

    async def save(self, record: OAuthStateRecord) -> None:
        self.records[record.state] = record

    async def consume(
        self, state: str, provider: str, *, user_id=None
    ) -> OAuthStateRecord | None:
        from apps.connections.errors import OAuthStateError

        record = self.records.get(state)
        if record is None or record.provider != provider:
            return None
        if user_id is not None and str(record.user_id) != str(user_id):
            raise OAuthStateError("state_mismatch")
        del self.records[state]
        return record


class MemoryLedger:
    def __init__(self) -> None:
        self.entries: dict[tuple, object] = {}
        self.log: list[tuple] = []
        self.errors: dict[tuple, str] = {}

    async def begin(self, scope, key, fingerprint):
        from apps.connections.publishing import LedgerEntry

        existing = self.entries.get((scope, key))
        if existing is not None:
            return existing, False
        entry = LedgerEntry(key=key, fingerprint=fingerprint, status="pending")
        self.entries[(scope, key)] = entry
        return entry, True

    async def restart(self, scope, key):
        from dataclasses import replace

        self.entries[(scope, key)] = replace(
            self.entries[(scope, key)], status="pending"
        )

    async def finish(self, scope, key, status, result=None, error=""):
        from dataclasses import replace

        self.errors[(scope, key)] = error
        self.log.append((key, status))
        self.entries[(scope, key)] = replace(
            self.entries[(scope, key)], status=status, result=result
        )
