from app.database import session_scope
from app.models.post import Post
from app.models.repurpose import RepurposeAttempt, UserAction, UserActionType
from app.tools.registry import tool


@tool(
    name="submit_action",
    description="Record the user's decision on a repurpose attempt: accept, edit, or reject it.",
    parameters={
        "type": "object",
        "properties": {
            "attempt_id": {"type": "integer"},
            "action": {"type": "string", "enum": [a.value for a in UserActionType]},
            "edited_text": {"type": "string", "description": "Required when action is 'edit'."},
        },
        "required": ["attempt_id", "action"],
    },
    cost="write",
    side_effects="writes_db",
)
async def submit_action(attempt_id: int, action: str, edited_text: str | None = None) -> dict:
    async with session_scope() as session:
        attempt = await session.get(RepurposeAttempt, attempt_id)
        if attempt is None:
            return {"error": f"no repurpose attempt with id {attempt_id}"}

        user_action = UserAction(attempt_id=attempt_id, action=UserActionType(action), edited_text=edited_text)
        session.add(user_action)
        await session.commit()
        await session.refresh(user_action)

    return {"action_id": user_action.id, "attempt_id": attempt_id, "action": action}


@tool(
    name="dismiss_alert",
    description="Dismiss a trending-post alert without drafting a repurpose for it.",
    parameters={"type": "object", "properties": {"post_id": {"type": "integer"}}, "required": ["post_id"]},
    side_effects="writes_db",
)
async def dismiss_alert(post_id: int) -> dict:
    async with session_scope() as session:
        post = await session.get(Post, post_id)
        if post is None:
            return {"error": f"no post with id {post_id}"}

        post.alert_dismissed = True
        session.add(post)
        await session.commit()

    return {"post_id": post_id, "dismissed": True}
