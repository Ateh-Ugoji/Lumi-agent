"""Agent tool that triggers voice learning. Reading and answering live in ``tools/voice.py``."""

from __future__ import annotations

from typing import Any

from lumi_ai.style.questions import STYLE_QUESTIONS
from lumi_ai.style.service import StyleService
from lumi_ai.tools.registry import ToolContext, ToolSpec


def build(service: StyleService) -> list[ToolSpec]:
    async def extract_voice_profile(
        ctx: ToolContext, platform: str = ""
    ) -> dict[str, Any]:
        result = await service.refresh_voice(ctx.profile_id, platform or None)  # type: ignore[arg-type]
        if result.status == "needs_style_questions":
            return {
                "needs_style_questions": True,
                "reason": result.reason,
                "questions": [
                    {"question_key": k, "question": q} for k, q in STYLE_QUESTIONS
                ],
            }
        if result.status == "failed":
            return {"error": f"voice extraction failed: {result.reason}"}
        voice = result.voice
        assert voice is not None
        return {
            "needs_style_questions": False,
            "voice_profile_id": voice.id,
            "version": voice.version,
            "platform": voice.platform,
            "posts_found": result.posts_found,
            "payload": dict(voice.payload),
        }

    return [
        ToolSpec(
            name="extract_voice_profile",
            description=(
                "Analyze the user's own recent posts to learn their writing voice. With fewer "
                "than the minimum posts it returns needs_style_questions and the questions to ask."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "platform": {
                        "type": "string",
                        "description": "Optional platform for a platform-specific voice; omit for the general voice.",
                    }
                },
            },
            handler=extract_voice_profile,
            cost="llm",
            side_effects="writes_db",
            cache_ttl=0,
        )
    ]
