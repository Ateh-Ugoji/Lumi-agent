"""Voice tools: read the learned voice profile and record cold-start style answers."""

from __future__ import annotations

from typing import Any

from lumi_ai.ports import StyleAnswerIn, VoiceStore
from lumi_ai.tools.registry import ToolContext, ToolSpec


def build(voice: VoiceStore) -> list[ToolSpec]:
    async def get_voice_profile(ctx: ToolContext, platform: str = "") -> dict[str, Any]:
        current = await voice.current_voice(ctx.profile_id, platform or None)  # type: ignore[arg-type]
        if current is None:
            return {"found": False}
        return {
            "found": True,
            "platform": current.platform,
            "version": current.version,
            "source": current.source,
            "payload": dict(current.payload),
            "example_post_ids": list(current.example_post_ids),
        }

    async def answer_style_questions(
        ctx: ToolContext, answers: list[dict[str, Any]]
    ) -> dict[str, Any]:
        cleaned: list[StyleAnswerIn] = []
        for item in answers or []:
            key, text = (
                str(item.get("question_key") or "").strip(),
                str(item.get("answer") or "").strip(),
            )
            if key and text:
                cleaned.append(StyleAnswerIn(question_key=key, answer=text))
        if not cleaned:
            return {
                "error": "answers must hold at least one item with question_key and answer"
            }
        await voice.save_style_answers(ctx.profile_id, cleaned)
        return {"profile_id": ctx.profile_id, "recorded": len(cleaned)}

    return [
        ToolSpec(
            name="get_voice_profile",
            description="Fetch the current voice profile for a profile, if one exists.",
            parameters={
                "type": "object",
                "properties": {
                    "profile_id": {"type": "integer"},
                    "platform": {
                        "type": "string",
                        "description": "Optional platform; omit for the profile's general voice.",
                    },
                },
                "required": ["profile_id"],
            },
            handler=get_voice_profile,
        ),
        ToolSpec(
            name="answer_style_questions",
            description=(
                "Record the user's answers to style fallback questions when there isn't enough "
                "post history."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "profile_id": {"type": "integer"},
                    "answers": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "question_key": {"type": "string"},
                                "answer": {"type": "string"},
                            },
                            "required": ["question_key", "answer"],
                        },
                    },
                },
                "required": ["profile_id", "answers"],
            },
            handler=answer_style_questions,
            side_effects="writes_db",
            cache_ttl=0,
        ),
    ]
