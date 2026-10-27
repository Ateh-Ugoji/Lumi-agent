"""In-memory McpStore and a scripted McpTransport."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from apps.connections.config import ConnectionsConfig
from apps.connections.mcp.connectors import MCPConnector
from apps.connections.mcp.gateway import (
    McpGatewayCore,
    PendingWrite,
    RemoteResult,
    RemoteTool,
)
from apps.connections.mcp.google import GoogleOAuth
from apps.connections.providers.base import TokenSet

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)

DRIVE_TOOLS = [
    RemoteTool("search_files", "Search Drive.", {"type": "object"}),
    RemoteTool("create_file", "Create a file.", {"properties": {"title": {}}}),
    RemoteTool("files.get v2", "Odd name.", {"type": "object"}),
]
DOCS_TOOLS = [
    RemoteTool("read_doc", "Read a doc.", {"type": "object"}),
    RemoteTool("batch_update", "Edit a doc.", {"type": "object"}),
]


class MemoryMcpStore:
    def __init__(self) -> None:
        self.owners: dict[int, int] = {1: 10}  # profile -> user
        self.tokens: dict[int, TokenSet] = {
            10: TokenSet(
                access_token="AT-FAKE",
                refresh_token="RT-FAKE",
                expires_at=NOW + timedelta(hours=1),
            )
        }
        self.pending: dict[int, PendingWrite] = {}
        self.saved: list[TokenSet] = []

    async def owner_of(self, profile_id: int) -> int | None:
        return self.owners.get(profile_id)

    async def load_tokens(self, user_id: int) -> TokenSet | None:
        return self.tokens.get(user_id)

    async def save_tokens(self, user_id: int, tokens: TokenSet) -> None:
        self.tokens[user_id] = tokens
        self.saved.append(tokens)

    async def park(self, write: PendingWrite) -> PendingWrite | None:
        held = self.pending.get(write.profile_id)
        if (
            held is not None
            and held.expires_at > NOW
            and held.confirmation_id != write.confirmation_id
        ):
            return held
        self.pending[write.profile_id] = write
        return None

    async def claim(self, profile_id: int) -> PendingWrite | None:
        return self.pending.pop(profile_id, None)


class FakeTransport:
    """Records every session it opens and every tool call, and can be told to fail or hang."""

    def __init__(self) -> None:
        self.tools = {"gdrive": list(DRIVE_TOOLS), "gdocs": list(DOCS_TOOLS)}
        self.opened: list[tuple[str, str]] = []  # (connector, bearer)
        self.calls: list[tuple[str, str, dict]] = []
        self.results: dict[str, RemoteResult] = {}
        self.fail_with: Exception | None = None
        self.hang = False

    @asynccontextmanager
    async def open(self, connector: MCPConnector, access_token: str):
        self.opened.append((connector.name, access_token))
        if self.hang:
            await asyncio.sleep(3600)
        if self.fail_with is not None:
            raise self.fail_with
        yield _Session(self, connector.name)


class _Session:
    def __init__(self, owner: FakeTransport, connector: str) -> None:
        self._owner, self._connector = owner, connector

    async def list_tools(self) -> list[RemoteTool]:
        return self._owner.tools[self._connector]

    async def call_tool(self, name: str, arguments: Mapping[str, Any]) -> RemoteResult:
        self._owner.calls.append((self._connector, name, dict(arguments)))
        return self._owner.results.get(name, RemoteResult(f"ran {name}"))


class Clock:
    def __init__(self) -> None:
        self.now = NOW
        self.mono = 1000.0

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)
        self.mono += seconds


def build(
    *,
    env: Mapping[str, str] | None = None,
    oauth_handler=None,
    config_env: Mapping[str, str] | None = None,
):
    store, transport, clock = MemoryMcpStore(), FakeTransport(), Clock()
    config = ConnectionsConfig.from_env(
        {
            "GOOGLE_OAUTH_CLIENT_ID": "g-id",
            "GOOGLE_OAUTH_CLIENT_SECRET": "g-sec",
            **(config_env or {}),
        }
    )
    oauth = GoogleOAuth(
        config,
        transport=httpx.MockTransport(
            oauth_handler
            or (
                lambda r: httpx.Response(
                    200, json={"access_token": "AT-NEW", "expires_in": 3600}
                )
            )
        ),
        clock=lambda: clock.now,
    )
    gateway = McpGatewayCore(
        store,
        transport,
        oauth,
        config,
        env or {},
        clock=lambda: clock.now,
        monotonic=lambda: clock.mono,
    )
    return gateway, store, transport, clock
