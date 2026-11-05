"""Config-driven registry of MCP connector servers.

Adding a connector = adding one `MCPConnector` entry below (name, server URL,
auth method, scopes, enabled toolset). No new code: the client
(`app/services/mcp.py`) discovers each server's tools with `tools/list`,
converts them to OpenAI-style function specs for the agent loop, and dispatches
`tools/call` through the same registry path as native tools.

Why Lumi is its own MCP client: the agent runs on Groq/OpenRouter behind the
OpenAI SDK, so Anthropic's cloud-side MCP connector (their beta
`mcp_servers` request field) cannot apply here. A local MCP client works with
any OpenAI-compatible provider and additionally supports localhost/stdio
servers, which a cloud-side connector can never reach.

Auth methods (`auth`):
- "google_oauth": Bearer token from the `mcp_auth_accounts` DB table (one row
  per auth account; Google's consent flow lives in `app/routers/mcp_google.py`).
- "bearer_env":   static Bearer token read from the env var named by
  `bearer_env` — for future self-hosted/company MCP servers.
- "none":         no Authorization header (public servers).

Write safety (`confirm_writes`): tools whose names contain a write verb
(create/update/delete/...) never execute on first call — the loop stores a
pending confirmation and only runs it after the user confirms in chat
(`app/services/mcp.py:requires_confirmation`).
"""

import os
import re
from dataclasses import dataclass, field
from urllib.parse import urlencode

GOOGLE_AUTH_ACCOUNT = "google"

# Scopes (Google's official Workspace-MCP scope set; see docs/mcp-connectors.md).
DRIVE_READONLY_SCOPE = "https://www.googleapis.com/auth/drive.readonly"
DRIVE_FILE_SCOPE = "https://www.googleapis.com/auth/drive.file"  # minimal write: only files this app creates
DOCS_SCOPE = "https://www.googleapis.com/auth/documents"  # create/format Google Docs

GOOGLE_CONSENT_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"

SANITIZER = re.compile(r"[^A-Za-z0-9_\-]")


@dataclass(frozen=True)
class MCPConnector:
    name: str  # namespace prefix for its tools: mcp__<name>__<tool>
    url: str  # Streamable-HTTP MCP endpoint (public HTTPS for remote servers)
    auth: str = "none"  # "google_oauth" | "bearer_env" | "none"
    scopes: tuple[str, ...] = ()  # consent-time scopes (google_oauth only)
    bearer_env: str | None = None  # env var holding the token (bearer_env only)
    enabled_env: str | None = None  # env var toggling this connector (default: on)
    allowed_tools: tuple[str, ...] | None = None  # expose only these server tool names; None = all
    confirm_writes: bool = True  # gate write/edit/delete tools behind user confirmation
    extra: dict = field(default_factory=dict)  # reserved for future connectors


CONNECTORS: tuple[MCPConnector, ...] = (
    MCPConnector(
        name="gdrive",
        url="https://drivemcp.googleapis.com/mcp/v1",
        auth="google_oauth",
        scopes=(DRIVE_READONLY_SCOPE, DRIVE_FILE_SCOPE),
        enabled_env="MCP_GDRIVE_ENABLED",
    ),
    MCPConnector(
        name="gdocs",
        url="https://docsmcp.googleapis.com/mcp/v1",
        auth="google_oauth",
        scopes=(DOCS_SCOPE,),
        enabled_env="MCP_GDOCS_ENABLED",
    ),
)


def get_connector(name: str) -> MCPConnector | None:
    for connector in CONNECTORS:
        if connector.name == name:
            return connector
    return None


def connector_enabled(connector: MCPConnector) -> bool:
    """Env toggle for one connector: `MCP_<NAME>_ENABLED`, default enabled."""
    if not connector.enabled_env:
        return True
    return os.environ.get(connector.enabled_env, "true").strip().lower() not in ("0", "false", "off", "no")


def tool_spec_name(connector: MCPConnector, tool_name: str) -> str:
    """OpenAI function name for an MCP tool. The API only allows [A-Za-z0-9_-],
    so exotic server-side names are sanitized (the original name is kept for
    the actual tools/call)."""
    return f"mcp__{connector.name}__{SANITIZER.sub('_', tool_name)}"


def google_scope_union() -> list[str]:
    """Every scope requested by every google_oauth connector, deduped, stable order."""
    scopes: list[str] = []
    for connector in CONNECTORS:
        if connector.auth != "google_oauth":
            continue
        for scope in connector.scopes:
            if scope not in scopes:
                scopes.append(scope)
    return scopes


def google_consent_url(state: str, redirect_uri: str, client_id: str) -> str:
    """Google's consent-page URL for the union of all google_oauth connectors.

    `access_type=offline` + `prompt=consent` are required to receive a refresh
    token (Google only returns one on first consent or forced re-consent).
    """
    params = urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(google_scope_union()),
            "access_type": "offline",
            "prompt": "consent",
            "include_granted_scopes": "true",
            "state": state,
        }
    )
    return f"{GOOGLE_CONSENT_URL}?{params}"
