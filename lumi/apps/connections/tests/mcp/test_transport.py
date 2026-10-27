"""``SdkMcpTransport`` against a real MCP server on loopback. No external network."""

from __future__ import annotations

import socket
import threading
import time
from collections.abc import Iterator

import pytest
import uvicorn
from mcp.server.mcpserver import MCPServer

from apps.connections.mcp import connectors
from apps.connections.mcp import gateway as gateway_module
from apps.connections.mcp.connectors import MCPConnector
from apps.connections.mcp.gateway import McpGatewayCore
from apps.connections.mcp.transport import SdkMcpTransport as _SdkMcpTransport

from .fakes import build

SEEN_AUTH: list[str] = []


class SdkMcpTransport(_SdkMcpTransport):
    """The real transport, but it refuses any host that is not loopback."""

    def open(self, connector: MCPConnector, access_token: str):
        assert connector.url.startswith("http://127.0.0.1:"), connector.url
        return super().open(connector, access_token)


def make_app():
    server = MCPServer("fake-drive")

    @server.tool()
    def search_files(q: str) -> str:
        """Search files."""
        return f"found:{q}"

    @server.tool()
    def create_file(title: str) -> str:
        """Create a file."""
        return f"created:{title}"

    inner = server.streamable_http_app()

    async def app(scope, receive, send):
        if scope["type"] == "http":
            for key, value in scope["headers"]:
                if key == b"authorization":
                    SEEN_AUTH.append(value.decode())
        await inner(scope, receive, send)

    return app


@pytest.fixture(scope="module")
def server_url() -> Iterator[str]:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    config = uvicorn.Config(make_app(), host="127.0.0.1", port=port, log_level="error")
    uv = uvicorn.Server(config)
    thread = threading.Thread(target=uv.run, daemon=True)
    thread.start()
    for _ in range(100):
        if uv.started:
            break
        time.sleep(0.05)
    assert uv.started, "loopback MCP server did not start"
    yield f"http://127.0.0.1:{port}/mcp"
    uv.should_exit = True
    thread.join(timeout=5)


async def test_lists_and_calls_tools_with_the_bearer_header(server_url):
    connector = MCPConnector(name="gdrive", url=server_url)
    SEEN_AUTH.clear()
    async with SdkMcpTransport().open(connector, "AT-FAKE") as session:
        tools = {t.name: t for t in await session.list_tools()}
        assert set(tools) == {"search_files", "create_file"}
        assert tools["search_files"].input_schema["type"] == "object"
        result = await session.call_tool("search_files", {"q": "plan"})
    assert result.text == "found:plan" and not result.is_error
    assert SEEN_AUTH and set(SEEN_AUTH) == {"Bearer AT-FAKE"}


async def test_a_tool_error_is_flagged_not_raised(server_url):
    connector = MCPConnector(name="gdrive", url=server_url)
    async with SdkMcpTransport().open(connector, "AT-FAKE") as session:
        result = await session.call_tool("search_files", {})  # missing argument
    assert result.is_error


async def test_the_whole_gateway_over_the_real_transport(server_url, monkeypatch):
    fake, store, _, _ = build()
    local = (MCPConnector(name="gdrive", url=server_url),)
    monkeypatch.setattr(connectors, "CONNECTORS", local)
    monkeypatch.setattr(gateway_module, "CONNECTORS", local)
    real = McpGatewayCore(
        store,
        SdkMcpTransport(),
        fake._oauth,
        fake._config,
        {},
        clock=fake._clock,
        monotonic=fake._monotonic,
    )
    names = {s.name: s for s in await real.list_tools(1)}
    assert set(names) == {"mcp__gdrive__search_files", "mcp__gdrive__create_file"}
    assert names["mcp__gdrive__create_file"].requires_confirmation
    read = await real.call(1, "mcp__gdrive__search_files", {"q": "x"})
    assert read.status == "ok" and read.payload["content"] == "found:x"
    parked = await real.call(1, "mcp__gdrive__create_file", {"title": "T"})
    assert parked.status == "confirmation_required"
    done = await real.resolve_pending(1, "yes")
    assert done is not None and done.result["content"] == "created:T"
