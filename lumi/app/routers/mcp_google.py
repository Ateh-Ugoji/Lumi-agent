"""Google OAuth for the MCP connectors (`/mcp/google/*`).

The MCP servers (Google's official Drive + Docs endpoints) are reached with a
Bearer access token that ONLY the user can grant, so Lumi runs the consent flow
itself: `/mcp/google/connect` sends the browser to Google's consent page (union
of every `auth="google_oauth"` connector's scopes, `access_type=offline` +
`prompt=consent` so a refresh token is issued), and `/mcp/google/callback`
exchanges the code and stores the tokens in `mcp_auth_accounts`.

Secrets rule: the OAuth client id/secret are env-only
(`GOOGLE_OAUTH_CLIENT_ID` / `GOOGLE_OAUTH_CLIENT_SECRET`); access/refresh
tokens live in the DB and are never logged or echoed.

Known gaps (same class as the PFM callback): the callback answers the browser
with bare JSON instead of redirecting back into the SPA, and the `state`
anti-CSRF values live in this process's memory (fine for the single-worker
demo; a multi-worker deploy needs them in the DB or a signed cookie).
"""

import logging
import secrets
import time

from fastapi import APIRouter
from fastapi.responses import JSONResponse, RedirectResponse

from app.config import get_settings
from app.services import mcp as mcp_service
from app.services.mcp_connectors import google_consent_url

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/mcp/google", tags=["mcp"])

STATE_TTL_SECONDS = 600  # consent round-trip budget
_states: dict[str, float] = {}  # state -> created (monotonic)


def _prune_states() -> None:
    now = time.monotonic()
    for state, created in list(_states.items()):
        if now - created > STATE_TTL_SECONDS:
            _states.pop(state, None)


@router.get("/connect")
async def connect():
    """Send the browser to Google's consent page for every Google MCP connector.

    Missing OAuth client config answers an honest 503 (never a fabricated URL).
    """
    settings = get_settings()
    if not settings.google_oauth_client_id or not settings.google_oauth_client_secret:
        # Honest 503 (never a fabricated consent URL); names env vars, no values.
        return JSONResponse(
            status_code=503,
            content={
                "error": "google_oauth_not_configured",
                "detail": (
                    "Set GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET "
                    "(see docs/mcp-connectors.md for the Google Cloud setup steps)."
                ),
            },
        )
    _prune_states()
    state = secrets.token_urlsafe(24)
    _states[state] = time.monotonic()
    url = google_consent_url(state, settings.google_oauth_redirect_uri, settings.google_oauth_client_id)
    return RedirectResponse(url, status_code=302)


@router.get("/callback")
async def callback(code: str | None = None, state: str | None = None, error: str | None = None):
    """Google redirected here after consent: exchange `code` for tokens."""
    if error:
        # The user denied or Google refused — honest report, nothing stored.
        logger.info("mcp google: consent not granted (%s)", error)
        return {"connected": False, "error": error}
    if not code:
        return {"connected": False, "error": "missing_code"}
    if not state or _states.pop(state, None) is None:
        return {"connected": False, "error": "invalid_state"}
    try:
        result = await mcp_service.exchange_google_code(code)
    except mcp_service.MCPAuthError as exc:
        logger.warning("mcp google: token exchange failed: %s", exc)
        return {"connected": False, "error": str(exc)}
    return result


@router.get("/status")
async def status():
    """Is Google connected (plus expiry/scopes)? Never returns token values.

    `configured` says whether the OAuth client env vars exist at all, so the
    frontend can explain an unconfigured server instead of offering a connect
    button that would dead-end on the connect route's honest 503.
    """
    settings = get_settings()
    info = await mcp_service.google_token_info()
    info["configured"] = bool(
        settings.google_oauth_client_id and settings.google_oauth_client_secret
    )
    info["connect_path"] = "/mcp/google/connect"
    return info
