from sqlmodel import select

from app.database import session_scope
from app.models.activity import UserActivity
from app.tools.registry import tool


@tool(
    name="get_user_activity",
    description=(
        "Recent non-original activity for the profile: replies (the user's own words) "
        "and retweets (content they shared from others — NEVER attribute retweet text "
        "to the user). Use when you need deeper context on who the user is: e.g. "
        "connecting something to a recent opinion they expressed in replies "
        "('since you said X…'), or when they reference something they said outside "
        "their main posts. Replies reveal their thinking; retweets reveal their interests."
    ),
    parameters={
        "type": "object",
        "properties": {
            "profile_id": {"type": "integer"},
            "kind": {"type": "string", "enum": ["reply", "retweet", "all"], "default": "all"},
            "limit": {"type": "integer", "default": 15},
        },
        "required": ["profile_id"],
    },
    side_effects="none",
)
async def get_user_activity(profile_id: int, kind: str = "all", limit: int = 15) -> dict:
    limit = max(1, min(limit, 50))
    async with session_scope() as session:
        stmt = select(UserActivity).where(UserActivity.profile_id == profile_id)
        if kind in ("reply", "retweet"):
            stmt = stmt.where(UserActivity.kind == kind)
        activity = (
            await session.exec(stmt.order_by(UserActivity.published_at.desc()).limit(limit))
        ).all()

    return {
        "activity": [
            {
                "kind": item.kind,
                "caption": item.caption,
                "published_at": item.published_at.isoformat(),
            }
            for item in activity
        ],
        "count": len(activity),
    }
