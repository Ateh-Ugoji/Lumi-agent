from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlmodel import select

from app.background.bootstrap import schedule_profile_bootstrap
from app.database import session_scope
from app.models.profile import Profile
from app.services.pfm import PFMClient

router = APIRouter(prefix="/pfm", tags=["pfm"])


class ConnectRequest(BaseModel):
    platform: str
    external_id: str = "lumi_user"


@router.post("/connect")
async def create_connect_url(payload: ConnectRequest) -> dict:
    """Generate OAuth connect URL using Post for Me."""
    client = PFMClient()
    try:
        # Post for Me requires posts/feeds to access history & metrics (read/write is rejected)
        permissions = ["posts", "feeds"]
        result = await client.create_auth_url(payload.platform, payload.external_id, permissions)
        return result
    finally:
        await client.aclose()


@router.get("/callback")
async def pfm_callback(
    is_success: str = Query(..., alias="isSuccess"),
    account_ids: str = Query("", alias="accountIds"),
    error: str | None = Query(None),
) -> dict:
    """Post for Me redirects here after the user completes (or abandons) the OAuth connect flow.

    This URL must be registered as the project's redirect URL in the Post for Me dashboard —
    it can't be set via the API when using Post for Me's system credentials.
    """
    if is_success != "true" or not account_ids:
        return {"connected": False, "error": error or "no accounts connected"}

    client = PFMClient()
    try:
        connected = []
        async with session_scope() as session:
            for account_id in account_ids.split(","):
                account = await client.get_social_account(account_id)
                metadata = account.get("metadata") or {}
                display_name = metadata.get("display_name") or account["username"]

                profile = (
                    await session.exec(select(Profile).where(Profile.pfm_account_id == account_id))
                ).first()
                if profile is None:
                    profile = Profile(name=display_name, handle=account["username"], pfm_account_id=account_id)
                else:
                    profile.handle = account["username"]
                    profile.name = display_name

                session.add(profile)
                await session.commit()
                await session.refresh(profile)
                connected.append({"profile_id": profile.id, "handle": profile.handle})
    finally:
        await client.aclose()

    for item in connected:
        if item.get("profile_id"):
            schedule_profile_bootstrap(item["profile_id"])

    return {"connected": True, "profiles": connected}
