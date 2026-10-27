"""The ``McpGateway`` port for Google Drive and Docs, scoped to one profile.

Pure core: the database (tokens, parked writes) and the network (the MCP session) come in
through ``McpStore`` and ``McpTransport``. Django's implementation is ``DjangoMcpStore`` in
``stores.py``; the real session is ``SdkMcpTransport`` in ``transport.py``.

Rules that do not bend:

* A write tool never runs on the first call. It is parked in the database and runs only after
  the user's next message is a clear yes. Any other message cancels it.
* A parked write is claimed with one atomic delete, so two workers cannot both run it.
* An exception never carries its message into the model's context. The error names the tool
  and the exception class, and tells the model not to claim success. A tool-level error the
  server returns on purpose is treated like any other tool output.
* Only tools the server listed (and the allow-list kept) can be called.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Callable, Mapping
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from lumi_ai.ports import McpCallResult, McpPendingResolution, McpToolSpec

from ..config import ConnectionsConfig
from ..errors import ProviderAuthError, SocialDataError
from ..providers.base import TokenSet
from .connectors import (
    CONNECTORS,
    MCPConnector,
    connector_enabled,
    get_connector,
    is_confirmation,
    mcp_enabled,
    requires_confirmation,
    tool_spec_name,
)
from .google import GoogleOAuth

logger = logging.getLogger(__name__)

RESULT_CHAR_LIMIT = 12000
REFRESH_MARGIN = timedelta(seconds=120)
PENDING_TTL = timedelta(minutes=30)
FAILURE_CACHE_SECONDS = 60.0


@dataclass(frozen=True, slots=True)
class RemoteTool:
    name: str
    description: str = ""
    input_schema: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RemoteResult:
    text: str
    is_error: bool = False


class McpSession(Protocol):
    async def list_tools(self) -> list[RemoteTool]: ...

    async def call_tool(
        self, name: str, arguments: Mapping[str, Any]
    ) -> RemoteResult: ...


class McpTransport(Protocol):
    def open(
        self, connector: MCPConnector, access_token: str
    ) -> AbstractAsyncContextManager[McpSession]: ...


@dataclass(frozen=True, slots=True)
class PendingWrite:
    user_id: int
    profile_id: int
    tool: str  # name the model used
    server_tool: str  # real name on the server
    arguments: Mapping[str, Any]
    summary: str
    expires_at: datetime


class McpStore(Protocol):
    async def owner_of(self, profile_id: int) -> int | None:
        """User who owns the profile, or ``None``."""
        ...

    async def load_tokens(self, user_id: int) -> TokenSet | None: ...

    async def save_tokens(self, user_id: int, tokens: TokenSet) -> None: ...

    async def park(self, write: PendingWrite) -> None:
        """Store the write. A profile has one parked write: a new one replaces it."""
        ...

    async def claim(self, profile_id: int) -> PendingWrite | None:
        """Return the parked write and delete it in one atomic step."""
        ...


class NotConnected(Exception):
    """Google is not connected for this user, or the grant is dead."""


@dataclass(slots=True)
class _Discovery:
    fetched_at: float
    specs: list[McpToolSpec]
    originals: dict[str, str]  # model-facing name -> server name
    failed: bool = False


class McpGatewayCore:
    def __init__(
        self,
        store: McpStore,
        transport: McpTransport,
        oauth: GoogleOAuth,
        config: ConnectionsConfig,
        env: Mapping[str, str],
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._store = store
        self._transport = transport
        self._oauth = oauth
        self._config = config
        self._env = env
        self._clock = clock
        self._monotonic = monotonic
        # Speed cache only. A stale entry costs one outdated tool list, never a wrong write.
        self._discovered: dict[tuple[int, str], _Discovery] = {}

    # --- port ----------------------------------------------------------------

    async def list_tools(self, profile_id: int) -> list[McpToolSpec]:
        if not mcp_enabled(self._env):
            return []
        user_id = await self._store.owner_of(profile_id)
        if user_id is None:
            return []
        specs: list[McpToolSpec] = []
        for connector in self._enabled():
            found = await self._discover(user_id, connector)
            if found is not None:
                specs.extend(found.specs)
        return specs

    async def call(
        self, profile_id: int, name: str, args: Mapping[str, Any]
    ) -> McpCallResult:
        connector = self._connector_of(name)
        if connector is None or not mcp_enabled(self._env):
            return _error(name, "unknown or disabled MCP tool")
        user_id = await self._store.owner_of(profile_id)
        if user_id is None:
            return _error(name, "no profile context")
        found = await self._discover(user_id, connector, allow_stale=True)
        server_tool = (found.originals.get(name) if found else None) or None
        if server_tool is None:
            return _error(name, "this tool is not offered to this user")
        arguments = dict(args or {})
        if connector.confirm_writes and requires_confirmation(server_tool):
            summary = _summarize(name, arguments)
            await self._store.park(
                PendingWrite(
                    user_id=user_id,
                    profile_id=profile_id,
                    tool=name,
                    server_tool=server_tool,
                    arguments=arguments,
                    summary=summary,
                    expires_at=self._clock() + PENDING_TTL,
                )
            )
            return McpCallResult(
                status="confirmation_required",
                payload={
                    "tool": name,
                    "message": (
                        "This action writes to the user's account and has NOT run. Tell the user "
                        "exactly what will run (the summary) and ask them to confirm, then stop "
                        "and wait. Never claim it happened. If they confirm, the system runs it "
                        "before your next reply and tells you the real outcome."
                    ),
                },
                summary=summary,
            )
        return await self._execute(connector, user_id, name, server_tool, arguments)

    async def resolve_pending(
        self, profile_id: int, user_message: str
    ) -> McpPendingResolution | None:
        pending = await self._store.claim(profile_id)
        if pending is None:
            return None
        if pending.expires_at <= self._clock():
            return McpPendingResolution(
                note=(
                    f"PENDING MCP ACTION OUTCOME: {pending.tool} expired before the user "
                    "answered and was NOT executed. Do not claim it ran."
                )
            )
        if not is_confirmation(user_message):
            return McpPendingResolution(
                note=(
                    f"PENDING MCP ACTION OUTCOME: the user did not confirm {pending.tool}. "
                    "It was NOT executed. If they still want it, call the tool again; it will "
                    "ask for confirmation again."
                )
            )
        connector = self._connector_of(pending.tool)
        if connector is None or not connector_enabled(connector, self._env):
            result = _error(pending.tool, "the connector is no longer enabled")
        else:
            result = await self._execute(
                connector,
                pending.user_id,
                pending.tool,
                pending.server_tool,
                pending.arguments,
            )
        outcome = {"status": result.status, **dict(result.payload)}
        if result.error:
            outcome["error"] = result.error
        return McpPendingResolution(
            note=(
                f"PENDING MCP ACTION OUTCOME: {pending.tool} was executed after the user "
                f"confirmed it. Real result: {json.dumps(outcome, ensure_ascii=False)[:4000]}. "
                "Report this exact outcome to the user, including any error."
            ),
            tool=pending.tool,
            arguments=pending.arguments,
            result=outcome,
        )

    # --- internals -----------------------------------------------------------

    def _enabled(self) -> list[MCPConnector]:
        return [c for c in CONNECTORS if connector_enabled(c, self._env)]

    @staticmethod
    def _connector_of(name: str) -> MCPConnector | None:
        parts = (name or "").split("__", 2)
        if len(parts) != 3 or parts[0] != "mcp":
            return None
        return get_connector(parts[1])

    async def _access_token(self, user_id: int) -> str:
        tokens = await self._store.load_tokens(user_id)
        if tokens is None:
            raise NotConnected
        if tokens.expires_within(REFRESH_MARGIN, now=self._clock()):
            try:
                tokens = await self._oauth.refresh(tokens)
            except ProviderAuthError as exc:
                raise NotConnected from exc
            await self._store.save_tokens(user_id, tokens)
        return tokens.access_token

    async def _discover(
        self, user_id: int, connector: MCPConnector, *, allow_stale: bool = False
    ) -> _Discovery | None:
        """Tool list for one user and connector. Never raises, never waits past the budget."""
        key = (user_id, connector.name)
        cached = self._discovered.get(key)
        now = self._monotonic()
        if cached is not None:
            ttl = (
                FAILURE_CACHE_SECONDS
                if cached.failed
                else float(self._config.mcp_tools_ttl_seconds)
            )
            if now - cached.fetched_at < ttl:
                return None if cached.failed and not cached.originals else cached
        try:
            fresh = await asyncio.wait_for(
                self._fetch(user_id, connector),
                timeout=float(self._config.mcp_refresh_timeout_seconds),
            )
        except NotConnected:
            logger.info("mcp %s: user %s is not connected", connector.name, user_id)
            self._discovered.pop(key, None)
            return None
        except Exception as exc:  # noqa: BLE001 - discovery is best effort
            logger.warning(
                "mcp %s: discovery failed (%s)", connector.name, type(exc).__name__
            )
            stale = cached.specs if cached else []
            originals = cached.originals if cached else {}
            self._discovered[key] = _Discovery(now, stale, originals, failed=True)
            return None if not (stale and allow_stale) else self._discovered[key]
        self._discovered[key] = fresh
        return fresh

    async def _fetch(self, user_id: int, connector: MCPConnector) -> _Discovery:
        token = await self._access_token(user_id)
        async with self._transport.open(connector, token) as session:
            tools = await session.list_tools()
        specs: list[McpToolSpec] = []
        originals: dict[str, str] = {}
        for tool in tools:
            if (
                connector.allowed_tools is not None
                and tool.name not in connector.allowed_tools
            ):
                continue
            gated = connector.confirm_writes and requires_confirmation(tool.name)
            schema = dict(tool.input_schema)
            if schema.get("type") != "object":
                schema = {
                    "type": "object",
                    **{k: v for k, v in schema.items() if k != "type"},
                }
            name = tool_spec_name(connector, tool.name)
            originals[name] = tool.name
            specs.append(
                McpToolSpec(
                    name=name,
                    description=tool.description
                    or f"MCP tool '{tool.name}' from the {connector.name} connector.",
                    parameters=schema,
                    cost="write" if gated else "free",
                    requires_confirmation=bool(gated),
                )
            )
        return _Discovery(self._monotonic(), specs, originals)

    async def _execute(
        self,
        connector: MCPConnector,
        user_id: int,
        name: str,
        server_tool: str,
        arguments: Mapping[str, Any],
    ) -> McpCallResult:
        try:
            token = await self._access_token(user_id)

            async def run() -> RemoteResult:
                async with self._transport.open(connector, token) as session:
                    return await session.call_tool(server_tool, arguments)

            # The budget covers opening the session too, not only the call.
            remote = await asyncio.wait_for(
                run(), timeout=float(self._config.mcp_call_timeout_seconds)
            )
        except NotConnected:
            return _error(
                name,
                "Google is not connected or the grant expired; the user must reconnect",
            )
        except (SocialDataError, TimeoutError, OSError) as exc:
            return _error(name, f"{type(exc).__name__}")
        except Exception as exc:  # noqa: BLE001 - one MCP failure must not end the turn
            logger.warning(
                "mcp %s: %s failed (%s)",
                connector.name,
                server_tool,
                type(exc).__name__,
            )
            return _error(name, f"{type(exc).__name__}")
        text = (remote.text or "(no content returned)")[:RESULT_CHAR_LIMIT]
        if remote.is_error:
            return McpCallResult(
                status="error",
                payload={"tool": name},
                error=f"{name} failed: {text}",
            )
        return McpCallResult(status="ok", payload={"tool": name, "content": text})


def _error(name: str, reason: str) -> McpCallResult:
    return McpCallResult(
        status="error",
        payload={"tool": name},
        error=f"{name} failed: {reason}. Do not claim it worked.",
    )


def _summarize(name: str, arguments: Mapping[str, Any]) -> str:
    text = json.dumps(dict(arguments), ensure_ascii=False, default=str)
    return f"{name} with {text[:500]}{'...' if len(text) > 500 else ''}"
