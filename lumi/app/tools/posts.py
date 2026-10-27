from sqlmodel import select

from app.database import session_scope
from app.models.post import Post
from app.tools.registry import tool


@tool(
    name="get_posts",
    description="List recent posts tracked for a profile.",
    parameters={
        "type": "object",
        "properties": {
            "profile_id": {"type": "integer"},
            "limit": {"type": "integer", "default": 20},
        },
        "required": ["profile_id"],
    },
    side_effects="none",
)
async def get_posts(profile_id: int, limit: int = 20) -> dict:
    async with session_scope() as session:
        posts = (
            await session.exec(
                select(Post).where(Post.profile_id == profile_id).order_by(Post.published_at.desc()).limit(limit)
            )
        ).all()

    return {
        "posts": [
            {"id": post.id, "caption": post.caption, "published_at": post.published_at.isoformat()}
            for post in posts
        ]
    }
