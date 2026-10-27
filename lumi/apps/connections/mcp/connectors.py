"""The registry of MCP connector servers, and the rules that decide what needs confirmation.

Adding a connector means adding one ``MCPConnector`` entry. The gateway discovers each
server's tools with ``tools/list`` and dispatches ``tools/call``; no other code changes.

Write safety: a tool the connector does not list as read-only never runs on the first call. It is
parked in the database and runs only after the user confirms in chat. Google's ``drive.file`` scope is the
second fence: a confirmed write can only touch files this app created.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlencode

GOOGLE_ACCOUNT = "google"

DRIVE_READONLY_SCOPE = "https://www.googleapis.com/auth/drive.readonly"
DRIVE_FILE_SCOPE = "https://www.googleapis.com/auth/drive.file"
DOCS_SCOPE = "https://www.googleapis.com/auth/documents"

GOOGLE_CONSENT_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_REVOKE_URL = "https://oauth2.googleapis.com/revoke"

_SANITIZER = re.compile(r"[^A-Za-z0-9_\-]")


@dataclass(frozen=True, slots=True)
class MCPConnector:
    name: str  # prefix of its tools: mcp__<name>__<tool>
    url: str  # Streamable HTTP endpoint
    scopes: tuple[str, ...] = ()
    enabled_env: str | None = None  # env var that switches this connector off
    allowed_tools: tuple[str, ...] | None = None  # None exposes every tool
    # Tools known to only read. Everything else, including a tool the server adds tomorrow, waits
    # for the user's yes. An empty tuple gates every tool.
    read_only_tools: tuple[str, ...] = ()
    confirm_writes: bool = True


CONNECTORS: tuple[MCPConnector, ...] = (
    MCPConnector(
        name="gdrive",
        url="https://drivemcp.googleapis.com/mcp/v1",
        scopes=(DRIVE_READONLY_SCOPE, DRIVE_FILE_SCOPE),
        enabled_env="MCP_GDRIVE_ENABLED",
        read_only_tools=(
            "search_files",
            "read_file_content",
            "download_file_content",
            "get_file_metadata",
            "get_file_permissions",
            "list_recent_files",
        ),
    ),
    MCPConnector(
        name="gdocs",
        url="https://docsmcp.googleapis.com/mcp/v1",
        scopes=(DOCS_SCOPE,),
        enabled_env="MCP_GDOCS_ENABLED",
        read_only_tools=("read_doc",),
    ),
)

# One Google grant covers every connector, so the consent asks for the union of their scopes.


def get_connector(name: str) -> MCPConnector | None:
    return next((c for c in CONNECTORS if c.name == name), None)


def connector_enabled(connector: MCPConnector, env: Mapping[str, str]) -> bool:
    if not connector.enabled_env:
        return True
    value = (env.get(connector.enabled_env) or "true").strip().lower()
    return value not in {"0", "false", "off", "no"}


def mcp_enabled(env: Mapping[str, str]) -> bool:
    return (env.get("MCP_ENABLED") or "true").strip().lower() not in {
        "0",
        "false",
        "off",
        "no",
    }


def tool_spec_name(connector: MCPConnector, tool_name: str) -> str:
    """Function name for the model. Only ``[A-Za-z0-9_-]`` is allowed, so odd names are
    sanitized. The server's own name is kept for the real call."""
    return f"mcp__{connector.name}__{_SANITIZER.sub('_', tool_name)}"


def google_scope_union() -> list[str]:
    scopes: list[str] = []
    for connector in CONNECTORS:
        for scope in connector.scopes:
            if scope not in scopes:
                scopes.append(scope)
    return scopes


def google_consent_url(
    *,
    state: str,
    redirect_uri: str,
    client_id: str,
    code_challenge: str | None = None,
) -> str:
    """``access_type=offline`` and ``prompt=consent`` are needed to receive a refresh token."""
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(google_scope_union()),
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": state,
    }
    if code_challenge:
        params["code_challenge"] = code_challenge
        params["code_challenge_method"] = "S256"
    return f"{GOOGLE_CONSENT_URL}?{urlencode(params)}"


# --- the write gate ----------------------------------------------------------

# Only a clear yes runs a parked write. Anything else cancels it.
_AFFIRMATIVE = re.compile(
    r"^\W*(?:yes|yep|yeah|yup|y|sure|absolutely|definitely|of course"
    r"|go ahead|go for it|do it|please do|proceed|confirm(?:ed)?|ok(?:ay)?"
    r"|sounds good|perfect|looks good|lgtm"
    r"|s[ií](?=\W*$|\s*[,.!])|dale|adelante|claro|confirmo|confirmado|hazlo|procede|vale|de acuerdo)\b",
    re.IGNORECASE,
)
# "yes, but not now" is not a confirmation.
_DEFER = re.compile(
    r"\b(?:but|wait|hold on|later|not (?:yet|now)|tomorrow"
    r"|pero|espera|despu[eé]s|todav[ií]a no|ahora no|ma[nñ]ana)\b",
    re.IGNORECASE,
)


def requires_confirmation(connector: MCPConnector, tool_name: str) -> bool:
    """Allow-list, not a block-list: only a tool the connector names as read-only runs without
    a yes. A name that merely looks harmless (``copy_file``) or is new is treated as a write."""
    if not connector.confirm_writes:
        return False
    return tool_name not in connector.read_only_tools


MAX_CONFIRMATION_WORDS = 6


def is_confirmation(message: str) -> bool:
    """A short, clear yes. A long message or a question is a new request, so it cancels the
    parked write: asking again costs one turn, running a write by mistake costs the user's file."""
    text = (message or "").strip()
    if "?" in text or len(text.split()) > MAX_CONFIRMATION_WORDS:
        return False
    return bool(_AFFIRMATIVE.match(text)) and not _DEFER.search(text)
