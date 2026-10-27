import logging

from app.services.pfm import PFMClient
from app.tools.registry import tool

logger = logging.getLogger(__name__)


@tool(
    name="connect_account",
    description=(
        "Generate an OAuth authorization link for the user to connect their X (Twitter) account via Post for Me. "
        "Do NOT ask the user for their handle first. Call this tool immediately whenever you need them to connect their account, "
        "and present the returned connect_url as a clear clickable markdown link: [Connect X](<connect_url>). "
        "The user will authorize directly on X, and the account is linked automatically."
    ),
    parameters={
        "type": "object",
        "properties": {
            "handle": {
                "type": "string",
                "description": "Optional X handle if known. If unknown, do not ask the user for it, leave blank.",
            },
        },
    },
    cost="write",
    # Write-tier, but the call itself only mints an auth URL — the DB write
    # happens later in the OAuth callback (routers/pfm.py), never here.
    side_effects="none",
)
async def connect_account(handle: str = "") -> dict:
    client = PFMClient()
    try:
        # Check if user's account is already connected
        clean_handle = (handle or "").lstrip("@").strip().lower()
        if not clean_handle or clean_handle == "atehofficial":
            try:
                acc = await client.get_social_account("spc_U8xOuoxKCYpKAbzUymPCd")
                if acc and acc.get("status") == "connected":
                    return {
                        "already_connected": True,
                        "handle": "AtehOfficial",
                        "status": "connected",
                        "message": "Account @AtehOfficial is already connected and active.",
                    }
            except Exception as exc:  # noqa: BLE001
                logger.debug("Could not verify existing account connection: %s", exc)


        external_id = (handle or "ateh_x_connect").lstrip("@").strip()
        auth_url = await client.create_auth_url(platform="x", external_id=external_id, permissions=["posts", "feeds"])
        return {
            "already_connected": False,
            "connect_url": auth_url.get("url"),
            "handle": handle or "AtehOfficial",
        }
    finally:
        await client.aclose()

