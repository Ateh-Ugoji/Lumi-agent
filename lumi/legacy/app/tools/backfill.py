from app.database import session_scope
from app.models.profile import Profile
from app.services.pfm import backfill_profile_posts
from app.tools.registry import tool


@tool(
    name="backfill_posts",
    description=(
        "Fetch a profile's post history and metrics from Post for Me and store them locally. "
        "Run this after connecting an account, or to refresh metrics for spike detection."
    ),
    parameters={
        "type": "object",
        "properties": {"profile_id": {"type": "integer"}},
        "required": ["profile_id"],
    },
    cost="credits",
    side_effects="writes_db",
)
async def backfill_posts(profile_id: int) -> dict:
    async with session_scope() as session:
        profile = await session.get(Profile, profile_id)
        if profile is None:
            return {"error": f"no profile with id {profile_id}"}
        if not profile.pfm_account_id:
            return {"error": "profile has no linked PFM account"}

        return await backfill_profile_posts(session, profile_id, profile.pfm_account_id)
