"""Django wiring of the ``McpGateway`` port.

``build_mcp_gateway()`` is what ``lumi_ai`` gets. It is cheap to build: the token and parked
write stores talk to the database only when a method runs.
"""

from __future__ import annotations

import os

from .config import ConnectionsConfig
from .mcp.gateway import McpGatewayCore
from .mcp.google import GoogleOAuth
from .mcp.transport import SdkMcpTransport
from .stores import DjangoMcpStore


def build_mcp_gateway() -> McpGatewayCore:
    config = ConnectionsConfig.from_env(os.environ)
    return McpGatewayCore(
        DjangoMcpStore(),
        SdkMcpTransport(timeout_seconds=float(config.mcp_call_timeout_seconds)),
        GoogleOAuth(config),
        config,
        os.environ,
    )
