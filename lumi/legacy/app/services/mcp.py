"""MCP client for remote connector servers (Google Drive + Docs first).

Lumi is its own MCP client (Anthropic's cloud-side MCP connector only exists on
Anthropic's API; this agent runs on Groq/OpenRouter behind the OpenAI SDK, so
tools are converted to OpenAI-style function specs instead — see
`app/services/mcp_connectors.py` for why and for the connector registry).

Flow, per connector:
- discovery: `tools/list` over Streamable HTTP, converted to OpenAI specs and
  cached (`mcp_tools_ttl_seconds`), merged into the agent's toolset by
  `app.tools.registry.list_tool_specs()` under namespaced names
  `mcp__<connector>__<tool>`.
- dispatch: `app.tools.registry.call_tool()` routes `mcp__*` names here;
  `tools/call` runs under its own `mcp_call_timeout_seconds` budget (the agent
  loop adds its 120s per-tool cap on top).

Write safety: a tool whose name contains a write verb (create/update/delete/…)
never executes on first call. The call stores a pending confirmation for the
current chat profile and returns `confirmation_required`; the loop then resolves
it from the user's next message (`resolve_pending`) — a clear yes executes the
tool and reports the REAL outcome, anything else cancels it. Google's own
restrictive `drive.file` scope is the second fence: even a confirmed write can
only touch files this app created.
"""

import asyncio
import json
import logging
import os
import re
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlmodel import select

from app.config import get_settings
from app.database import session_scope
from app.models.mcp_auth_account import MCPAuthAccount
from app.services.mcp_connectors import (
    CONNECTORS,
    GOOGLE_AUTH_ACCOUNT,
    GOOGLE_TOKEN_URL,
    MCPConnector,
    connector_enabled,
    get_connector,
    tool_spec_name,
)

logger = logging.getLogger(__name__)

RESULT_CHAR_LIMIT = 12000  # hard cap on one tool result payload (loop trims context further)
TOKEN_REFRESH_MARGIN = timedelta(seconds=120)
GOOGLE_ACCOUNT = GOOGLE_AUTH_ACCOUNT


class MCPAuthError(RuntimeError):
    """Connector auth is missing/expired — the message is written for the model."""


# --- process state -----------------------------------------------------------
# Tool specs cached per connector: connector -> (fetched_at_monotonic, specs).
# Original (unsanitized) server tool names, per connector: sanitized -> original.
_specs: dict[str, tuple[float, list[dict]]] = {}
_tool_names: dict[str, dict[str, str]] = {}
# Write-tool calls awaiting the user's yes: profile_id -> PendingConfirmation.
_pending: dict[int, "PendingConfirmation"] = {}


def _reset_state() -> None:
    """Test helper: drop caches and pending confirmations."""
    _specs.clear()
    _tool_names.clear()
    _pending.clear()


@dataclass
class PendingConfirmation:
    profile_id: int
    tool: str  # namespaced spec name, e.g. mcp__gdocs__create_document
    server_tool: str  # original name on the MCP server
    arguments: dict
    summary: str
    requested_at: float = field(default_factory=time.monotonic)


@dataclass
class PendingResolution:
    note: str  # model-facing system note with the real outcome
    tool: str | None = None  # set when a tool actually executed
    arguments: dict = field(default_factory=dict)
    result: Any = None


# --- write-confirmation classifier -------------------------------------------
# Exact word membership on the tool name ("create_document" -> {create, doc...}),
# so read tools like `get_file_created_time` (word "created") are NOT gated.
_WRITE_WORDS = frozenset(
    {
        "create", "update", "delete", "remove", "move", "trash", "write",
        "insert", "send", "rename", "share", "unshare", "upload", "modify",
        "patch", "clear", "purge", "revoke", "duplicate", "apply", "restore",
        "reorder", "add", "set",
    }
)
_WORD_SPLIT_RE = re.compile(r"[^A-Za-z0-9]+|(?<=[a-z0-9])(?=[A-Z])")

# A CLEAR yes executes a pending write; anything else cancels it (never run
# without explicit confirmation — over-asking beats over-running).
_AFFIRMATIVE_RE = re.compile(
    r"^\W*(?:yes|yep|yeah|yup|y|sure|absolutely|definitely|of course"
    r"|go ahead|go for it|do it|please do|proceed|confirm(?:ed)?|ok(?:ay)?"
    r"|sounds good|perfect|looks good|lgtm)\b",
    re.IGNORECASE,
)
# "yes, but not now" / "sure, wait" is NOT a confirmation — defer words veto it.
_DEFER_RE = re.compile(
    r"\b(?:but|wait|hold on|later|not (?:yet|now)|tomorrow)\b",
    re.IGNORECASE,
)


def requires_confirmation(tool_name: str) -> bool:
    """True when the MCP tool name contains a write verb (word-wise match)."""
    words = {w.lower() for w in _WORD_SPLIT_RE.split(tool_name or "") if w}
    return bool(words & _WRITE_WORDS)


def spec_cost(name: str) -> str:
    """Cost tier (L13 item 3) for an `mcp__*` spec name.

    Mirrors the dispatch gate in `call_tool`: a tool the connector gates behind
    a user confirmation is a `write`, everything else is `free`. Unknown
    connector/tool names are `free` — dispatch still raises the real
    "unknown MCP tool" error for them.
    """
    connector, server_tool = split_spec_name(name)
    if connector is None:
        return "free"
    return "write" if (connector.confirm_writes and requires_confirmation(server_tool)) else "free"


def split_spec_name(name: str) -> tuple[MCPConnector | None, str]:
    """`mcp__<connector>__<tool>` -> (connector, ORIGINAL server tool name)."""
    parts = (name or "").split("__", 2)
    if len(parts) != 3 or parts[0] != "mcp":
        return None, ""
    connector = get_connector(parts[1])
    if connector is None:
        return None, ""
    # `_tool_names` is keyed by the full spec name -> original name (sanitized
    # spec names like `files_list` must call the server's real `files.list`).
    original = _tool_names.get(connector.name, {}).get(name, parts[2])
    return connector, original


# --- tool specs ---------------------------------------------------------------


def _convert_tool(connector: MCPConnector, mcp_tool: Any) -> dict | None:
    """One MCP tool -> one OpenAI function spec, or None when allowlisted out."""
    server_name = getattr(mcp_tool, "name", "") or ""
    if connector.allowed_tools is not None and server_name not in connector.allowed_tools:
        return None
    schema = getattr(mcp_tool, "input_schema", None)
    schema = dict(schema) if isinstance(schema, dict) else {}
    if schema.get("type") != "object":
        schema = {"type": "object", **{k: v for k, v in schema.items() if k != "type"}}
    description = getattr(mcp_tool, "description", "") or ""
    return {
        "type": "function",
        "function": {
            "name": tool_spec_name(connector, server_name),
            "description": description or f"MCP tool '{server_name}' from the {connector.name} connector.",
            "parameters": schema,
        },
    }


def list_specs() -> list[dict]:
    """Cached MCP specs for every enabled connector (sync; called per turn)."""
    try:
        settings = get_settings()
    except Exception:  # noqa: BLE001 - never let config trouble break the toolset
        return []
    if not settings.mcp_enabled:
        return []
    specs: list[dict] = []
    for connector in CONNECTORS:
        if not connector_enabled(connector):
            continue
        cached = _specs.get(connector.name)
        if cached:
            specs.extend(cached[1])
    return specs


async def refresh_tools(force: bool = False) -> None:
    """Best-effort `tools/list` refresh for connectors whose cache expired.

    Never raises: an unreachable/unauthenticated connector simply contributes
    no tools this turn (its cache, if any, stays stale-but-working).
    """
    try:
        settings = get_settings()
    except Exception:  # noqa: BLE001
        return
    if not settings.mcp_enabled:
        return
    ttl = float(settings.mcp_tools_ttl_seconds)
    now = time.monotonic()
    for connector in CONNECTORS:
        if not connector_enabled(connector):
            continue
        cached = _specs.get(connector.name)
        if cached is not None and not force and now - cached[0] < ttl:
            continue
        try:
            specs = await asyncio.wait_for(
                _fetch_connector_tools(connector),
                timeout=float(settings.mcp_refresh_timeout_seconds),
            )
        except MCPAuthError as exc:
            logger.info("mcp %s: not connected (%s)", connector.name, exc)
            continue
        except Exception as exc:  # noqa: BLE001 - discovery is best-effort
            logger.warning("mcp %s: tool discovery failed: %s", connector.name, exc)
            continue
        if specs is not None:
            _specs[connector.name] = (now, specs)


async def _fetch_connector_tools(connector: MCPConnector) -> list[dict] | None:
    """Open a session, list tools, convert + allowlist-filter. None = not authed."""
    if not await _auth_ready(connector):
        return None
    headers = await _auth_headers(connector)
    names: dict[str, str] = {}
    async with _open_session(connector, headers) as session:
        result = await session.list_tools()
    specs: list[dict] = []
    for mcp_tool in getattr(result, "tools", None) or []:
        spec = _convert_tool(connector, mcp_tool)
        if spec is None:
            continue
        names[spec["function"]["name"]] = getattr(mcp_tool, "name", "") or ""
        specs.append(spec)
    _tool_names[connector.name] = names
    logger.info("mcp %s: discovered %d tools", connector.name, len(specs))
    return specs


# --- auth ---------------------------------------------------------------------


async def _auth_ready(connector: MCPConnector) -> bool:
    """Is this connector's credential present (before any network call)?"""
    if connector.auth == "none":
        return True
    if connector.auth == "bearer_env":
        return bool(os.environ.get(connector.bearer_env or "", ""))
    if connector.auth == "google_oauth":
        async with session_scope() as session:
            return await _load_auth_row(session) is not None
    return False


async def _auth_headers(connector: MCPConnector) -> dict[str, str]:
    if connector.auth == "none":
        return {}
    if connector.auth == "bearer_env":
        token = os.environ.get(connector.bearer_env or "", "")
    elif connector.auth == "google_oauth":
        token = await _google_access_token()
    else:
        token = ""
    return {"Authorization": f"Bearer {token}"} if token else {}


async def _load_auth_row(session: Any, account: str = GOOGLE_ACCOUNT) -> MCPAuthAccount | None:
    return (await session.exec(select(MCPAuthAccount).where(MCPAuthAccount.account == account))).first()


async def _google_access_token() -> str | None:
    """Current Google access token, transparently refreshed when near expiry."""
    async with session_scope() as session:
        row = await _load_auth_row(session)
        if row is None:
            return None
        access_token, refresh_token, expires_at = row.access_token, row.refresh_token, row.expires_at
    if expires_at is not None and expires_at - datetime.now(UTC) < TOKEN_REFRESH_MARGIN:
        return await _refresh_google_token(access_token, refresh_token)
    return access_token


async def _post_token_exchange(payload: dict) -> dict:
    """POST one form-encoded grant to Google's token endpoint. No secrets logged."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(GOOGLE_TOKEN_URL, data=payload)
    body: dict = {}
    try:
        parsed = response.json()
        if isinstance(parsed, dict):
            body = parsed
    except Exception:  # noqa: BLE001 - Google serves non-JSON error pages too
        logger.debug("mcp: token endpoint returned a non-JSON body (%s)", response.status_code)
    if response.status_code >= 400:
        error = str(body.get("error") or response.reason_phrase or "unknown_error")
        if error == "invalid_grant":
            raise MCPAuthError(
                "Google rejected the stored grant (expired or revoked). "
                "The user must reconnect Google at /mcp/google/connect before this tool can run."
            )
        raise MCPAuthError(f"Google token endpoint error: {error}")
    if not isinstance(body, dict) or not body.get("access_token"):
        raise MCPAuthError("Google token endpoint returned no access_token")
    return body


async def _persist_google_tokens(payload: dict) -> str:
    access_token = str(payload["access_token"])
    expires_in = payload.get("expires_in")
    try:
        expires_at = datetime.now(UTC) + timedelta(seconds=int(expires_in)) if expires_in else None
    except (TypeError, ValueError):
        expires_at = None
    async with session_scope() as session:
        row = await _load_auth_row(session)
        if row is None:
            row = MCPAuthAccount(account=GOOGLE_ACCOUNT, access_token=access_token)
            session.add(row)
        else:
            row.access_token = access_token
        # Google only echoes a refresh_token on first consent (or forced
        # re-consent); a response without one keeps the stored value.
        if payload.get("refresh_token"):
            row.refresh_token = str(payload["refresh_token"])
        row.token_type = str(payload.get("token_type") or "Bearer")
        if payload.get("scope"):
            row.scopes = str(payload["scope"])
        row.expires_at = expires_at
        row.updated_at = datetime.now(UTC)
        await session.commit()
    return access_token


async def _refresh_google_token(access_token: str, refresh_token: str | None) -> str:
    settings = get_settings()
    if not refresh_token:
        raise MCPAuthError(
            "The Google access token expired and no refresh token is stored. "
            "The user must reconnect Google at /mcp/google/connect."
        )
    payload = await _post_token_exchange(
        {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": settings.google_oauth_client_id,
            "client_secret": settings.google_oauth_client_secret,
        }
    )
    logger.info("mcp google: access token refreshed")
    return await _persist_google_tokens(payload)


async def exchange_google_code(code: str) -> dict:
    """OAuth callback: authorization code -> tokens, persisted to the DB."""
    settings = get_settings()
    payload = await _post_token_exchange(
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": settings.google_oauth_redirect_uri,
            "client_id": settings.google_oauth_client_id,
            "client_secret": settings.google_oauth_client_secret,
        }
    )
    await _persist_google_tokens(payload)
    logger.info("mcp google: consent stored")
    # Invalidation: the first consent unlocks tool discovery for both connectors.
    _specs.pop("gdrive", None)
    _specs.pop("gdocs", None)
    return {
        "connected": True,
        "account": GOOGLE_ACCOUNT,
        "scopes": str(payload.get("scope") or ""),
    }


async def google_token_info() -> dict:
    """Connection status for `/mcp/google/status` (no token values exposed)."""
    async with session_scope() as session:
        row = await _load_auth_row(session)
    if row is None:
        return {"connected": False}
    return {
        "connected": True,
        "scopes": row.scopes,
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
        "has_refresh_token": bool(row.refresh_token),
    }


# --- session + dispatch -------------------------------------------------------


@asynccontextmanager
async def _open_session(connector: MCPConnector, headers: dict[str, str]):
    """One Streamable-HTTP MCP session (opened per operation — simple, leak-free).

    mcp>=2 hands auth to a caller-owned httpx2 client instead of a headers
    kwarg; no headers means the default client (no Authorization header).
    """
    import httpx2
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    http_client = httpx2.AsyncClient(headers=headers) if headers else None
    try:
        async with streamable_http_client(connector.url, http_client=http_client) as streams:
            read_stream, write_stream = streams
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                yield session
    finally:
        if http_client is not None:
            await http_client.aclose()


def _result_payload(full_name: str, result: Any) -> dict:
    is_error = bool(getattr(result, "is_error", False))
    parts: list[str] = []
    for block in getattr(result, "content", None) or []:
        text = getattr(block, "text", None)
        if text:
            parts.append(str(text))
    text = "\n".join(parts).strip()
    structured = getattr(result, "structured_content", None)
    if not text and structured is not None:
        text = json.dumps(structured, ensure_ascii=False)
    if not text:
        text = "(no content returned)"
    text = text[:RESULT_CHAR_LIMIT]
    if is_error:
        return {"error": f"{full_name} failed: {text}"}
    return {"tool": full_name, "content": text}


async def _execute_remote(connector: MCPConnector, full_name: str, server_tool: str, arguments: dict) -> dict:
    """The single `tools/call` network seam (tests patch this). Returns the payload."""
    headers = await _auth_headers(connector)
    timeout = float(get_settings().mcp_call_timeout_seconds)
    async with _open_session(connector, headers) as session:
        result = await asyncio.wait_for(
            session.call_tool(server_tool, arguments or None), timeout=timeout
        )
    return _result_payload(full_name, result)


async def _execute(connector: MCPConnector, full_name: str, server_tool: str, arguments: dict) -> dict:
    """Execute a tool call; failures come back as honest error payloads, never raises."""
    try:
        return await _execute_remote(connector, full_name, server_tool, arguments or {})
    except MCPAuthError as exc:
        return {"error": str(exc)}
    except Exception as exc:  # noqa: BLE001 - one MCP failure must not kill the turn
        logger.warning("mcp %s: call %s failed: %s", connector.name, server_tool, exc)
        return {"error": f"{full_name} failed with {type(exc).__name__}: {exc}. Do not claim it worked."}


def _summarize(full_name: str, arguments: dict) -> str:
    args = json.dumps(arguments or {}, ensure_ascii=False)
    if len(args) > 500:
        args = args[:500] + "..."
    return f"{full_name} with {args}"


async def call_tool(name: str, arguments: dict) -> Any:
    """Entry point from `app.tools.registry.call_tool` for `mcp__*` names.

    Read tools execute immediately; write tools stop at the confirmation gate.
    """
    connector, server_tool = split_spec_name(name)
    if connector is None:
        raise ValueError(f"unknown MCP tool: {name}")
    arguments = dict(arguments or {})
    if not (connector.confirm_writes and requires_confirmation(server_tool)):
        return await _execute(connector, name, server_tool, arguments)

    from app.tools.registry import get_current_profile_id  # local: registry routes here

    profile_id = get_current_profile_id()
    if profile_id is None:
        return {
            "error": (
                f"{name} requires user confirmation but has no chat profile context; "
                "it was not executed."
            ),
        }
    _pending[profile_id] = PendingConfirmation(
        profile_id=profile_id,
        tool=name,
        server_tool=server_tool,
        arguments=arguments,
        summary=_summarize(name, arguments),
    )
    logger.info("mcp: confirmation required for %s (profile %s)", name, profile_id)
    return {
        "status": "confirmation_required",
        "tool": name,
        "summary": _summarize(name, arguments),
        "message": (
            "This action writes to the user's account and has NOT run. Tell the user exactly what "
            "will run (the summary above) and ask them to confirm, then STOP and wait for their "
            "reply. Never claim it happened. If they confirm, the system executes it before your "
            "next reply and tells you the real outcome to report."
        ),
    }


async def resolve_pending(profile_id: int, user_message: str) -> PendingResolution | None:
    """Resolve a pending write from the user's next message (called by the loop).

    A clear yes executes the tool and returns its REAL outcome; anything else
    cancels it. There is never a stale pending write: any next user message
    resolves (executes or cancels) it.
    """
    pending = _pending.pop(profile_id, None)
    if pending is None:
        return None
    user_text = (user_message or "").strip()
    if _AFFIRMATIVE_RE.match(user_text) and not _DEFER_RE.search(user_text):
        connector = get_connector(pending.tool.split("__", 2)[1])
        if connector is None:
            result: dict = {"error": f"connector for {pending.tool} is no longer configured; not executed."}
        else:
            result = await _execute(connector, pending.tool, pending.server_tool, pending.arguments)
        logger.info("mcp: pending %s executed for profile %s (error=%s)", pending.tool, profile_id, bool(result.get("error")))
        note = (
            f"PENDING MCP ACTION OUTCOME: {pending.tool} was executed after the user confirmed it. "
            f"Real result: {json.dumps(result, ensure_ascii=False)[:4000]}. "
            "Report this exact outcome to the user, including any error — never claim more."
        )
        return PendingResolution(note=note, tool=pending.tool, arguments=pending.arguments, result=result)
    logger.info("mcp: pending %s cancelled for profile %s (no confirmation)", pending.tool, profile_id)
    note = (
        f"PENDING MCP ACTION OUTCOME: the user did not confirm {pending.tool}. It was NOT executed. "
        "Do not claim it ran. If they still want it, call the tool again (it will re-request "
        "confirmation)."
    )
    return PendingResolution(note=note)
