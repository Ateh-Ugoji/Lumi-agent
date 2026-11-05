from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlmodel import func, select

from app.database import session_scope
from app.models.poll import PollConfig
from app.models.post import Post
from app.models.profile import Profile
from app.models.voice import VoiceProfile

router = APIRouter(prefix="/profiles", tags=["profiles"])

PLATFORM = "x"  # MVP targets X (Twitter) only


class ProfileSummary(BaseModel):
    id: int
    name: str
    platform: str = PLATFORM
    handle: str
    has_voice_profile: bool
    listening_active: bool
    # Weak-inferred posting timezone ("UTC+01:00" / IANA when confirmed).
    # timezone_source: "inferred" | "user_confirmed" — user confirmation always
    # wins and is never overwritten (the niche confirm endpoint is not built
    # yet; these fields expose current state for the frontend).
    timezone: str | None = None
    timezone_source: str | None = None


class ProfileListResponse(BaseModel):
    profiles: list[ProfileSummary]


class ProfileSelectResponse(BaseModel):
    profile_id: int
    name: str
    voice_profile_exists: bool
    post_count: int
    listening_active: bool


async def _has_voice_profile(session, profile_id: int) -> bool:
    result = (await session.exec(select(VoiceProfile).where(VoiceProfile.profile_id == profile_id))).first()
    return result is not None


async def _is_listening(session, profile_id: int) -> bool:
    config = (await session.exec(select(PollConfig).where(PollConfig.profile_id == profile_id))).first()
    return bool(config and config.is_active)


async def _post_count(session, profile_id: int) -> int:
    return (await session.exec(select(func.count(Post.id)).where(Post.profile_id == profile_id))).one()


USER_HANDLES = {"atehofficial", "ateh", "just_ateh"}
USER_PFM_IDS = {"spc_U8xOuoxKCYpKAbzUymPCd", "spc_VoWGXwlzvgGx9el6AtN1"}


@router.get("", response_model=ProfileListResponse)
async def list_profiles() -> ProfileListResponse:
    async with session_scope() as session:
        all_profiles = (await session.exec(select(Profile).order_by(Profile.id))).all()
        # Only show accounts belonging to this user (@AtehOfficial / @ateh / just_ateh)
        user_profiles = [
            p
            for p in all_profiles
            if p.handle.lower().lstrip("@") in USER_HANDLES or p.pfm_account_id in USER_PFM_IDS
        ]
        # Prioritize primary X account AtehOfficial first
        user_profiles = sorted(user_profiles, key=lambda p: 0 if p.handle.lower() == "atehofficial" else 1)

        summaries = [
            ProfileSummary(
                id=profile.id,
                name=profile.name,
                platform=profile.platform or "x",
                handle=profile.handle,
                has_voice_profile=await _has_voice_profile(session, profile.id),
                listening_active=await _is_listening(session, profile.id),
                timezone=profile.timezone,
                timezone_source=profile.timezone_source,
            )
            for profile in user_profiles
        ]

    return ProfileListResponse(profiles=summaries)




@router.post("/{profile_id}/select", response_model=ProfileSelectResponse)
async def select_profile(profile_id: int) -> ProfileSelectResponse:
    async with session_scope() as session:
        profile = await session.get(Profile, profile_id)
        if profile is None:
            raise HTTPException(status_code=404, detail=f"no profile with id {profile_id}")

        return ProfileSelectResponse(
            profile_id=profile.id,
            name=profile.name,
            voice_profile_exists=await _has_voice_profile(session, profile_id),
            post_count=await _post_count(session, profile_id),
            listening_active=await _is_listening(session, profile_id),
        )


@router.get("/{profile_id}/analytics")
async def get_profile_analytics_endpoint(profile_id: int) -> dict:
    from app.services.analytics import get_profile_analytics

    data = await get_profile_analytics(profile_id)
    if "error" in data:
        raise HTTPException(status_code=404, detail=data["error"])
    return data

