"""Real MCP session over Streamable HTTP, using the official ``mcp`` SDK.

The SDK is imported lazily so the rest of the package loads without it. Tests never reach
this module: they inject a fake ``McpTransport``. Each call opens a short-lived session with
the user's own bearer token, so nothing is shared between users.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from typing import Any

from .connectors import MCPConnector
from .gateway import McpSession, RemoteResult, RemoteTool


class _SdkSession:
    def __init__(self, session: Any) -> None:
        self._session = session

    async def list_tools(self) -> list[RemoteTool]:
        tools: list[RemoteTool] = []
        from mcp.types import PaginatedRequestParams

        cursor: str | None = None
        for _ in range(10):  # a bounded number of pages
            params = PaginatedRequestParams(cursor=cursor) if cursor else None
            page = await self._session.list_tools(params=params)
            tools.extend(
                RemoteTool(
                    name=t.name,
                    description=t.description or "",
                    input_schema=dict(t.input_schema or {}),
                )
                for t in page.tools
            )
            cursor = page.next_cursor
            if not cursor:
                break
        return tools

    async def call_tool(self, name: str, arguments: Mapping[str, Any]) -> RemoteResult:
        result = await self._session.call_tool(name, dict(arguments))
        parts = [
            block.text
            for block in (result.content or [])
            if getattr(block, "type", "") == "text" and getattr(block, "text", None)
        ]
        return RemoteResult(text="\n".join(parts), is_error=bool(result.is_error))


class SdkMcpTransport:
    def __init__(self, *, timeout_seconds: float = 30.0) -> None:
        self._timeout = timeout_seconds

    @asynccontextmanager
    async def open(
        self, connector: MCPConnector, access_token: str
    ) -> AsyncIterator[McpSession]:
        import httpx2
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client

        async with (
            httpx2.AsyncClient(
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=self._timeout,
                follow_redirects=False,
            ) as http_client,
            streamable_http_client(connector.url, http_client=http_client) as (
                read,
                write,
            ),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            yield _SdkSession(session)
