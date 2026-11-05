"""``submit_action``: the user's decision on a generated attempt."""

from __future__ import annotations

from typing import Any

from lumi_ai.ports import RepurposeStore
from lumi_ai.tools.registry import ToolContext, ToolSpec

ACTIONS = ["accept", "edit", "reject"]


def build(repurpose: RepurposeStore) -> ToolSpec:
    async def submit_action(
        ctx: ToolContext, attempt_id: int, action: str, edited_text: str | None = None
    ) -> dict[str, Any]:
        if action not in ACTIONS:
            return {"error": f"action must be one of: {', '.join(ACTIONS)}"}
        if action == "edit" and not (edited_text or "").strip():
            return {"error": "edited_text is required when action is 'edit'"}
        try:
            await repurpose.record_user_action(
                ctx.profile_id,
                attempt_id,
                action,
                edited_text,  # type: ignore[arg-type]
            )
        except LookupError:
            return {
                "error": f"no repurpose attempt with id {attempt_id} for this profile"
            }
        return {"attempt_id": attempt_id, "action": action}

    return ToolSpec(
        name="submit_action",
        description="Record the user's decision on a repurpose attempt: accept, edit, or reject it.",
        parameters={
            "type": "object",
            "properties": {
                "attempt_id": {"type": "integer"},
                "action": {"type": "string", "enum": ACTIONS},
                "edited_text": {
                    "type": "string",
                    "description": "Required when action is 'edit'.",
                },
            },
            "required": ["attempt_id", "action"],
        },
        handler=submit_action,
        cost="write",
        side_effects="writes_db",
        cache_ttl=0,
    )
