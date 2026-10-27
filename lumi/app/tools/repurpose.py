import json

from sqlmodel import select

from app.database import session_scope
from app.models.post import Post
from app.models.repurpose import RepurposeAttempt, RepurposeRequest
from app.models.voice import VoiceProfile
from app.services.repurpose_flow import run_platform_repurpose
from app.tools.registry import tool


def _normalize_phrases(value: object) -> list[str]:
    """Coerce the model's must_keep_phrases into a clean list of strings.

    LLMs sometimes pass the array as a JSON string ('["a", "b"]'); iterating
    that string checks individual characters and fails enforcement for every
    phrase containing punctuation.
    """
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("["):
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, list):
                return [str(p) for p in parsed if str(p).strip()]
        return [text] if text else []
    if isinstance(value, list):
        return [str(p) for p in value if str(p).strip()]
    return []


@tool(
    name="repurpose_caption",
    description=(
        "Draft a platform-optimized rewrite of a caption in the profile's voice (supports X, LinkedIn, TikTok, Instagram), "
        "and runs it through must-keep and semantic preservation checks. "
        "Pass either a post_id or source_text."
    ),
    parameters={
        "type": "object",
        "properties": {
            "profile_id": {"type": "integer"},
            "platform": {
                "type": "string",
                "description": "Target platform: 'x', 'linkedin', 'tiktok', or 'instagram' (default: 'x')",
            },
            "post_id": {"type": "integer"},
            "source_text": {"type": "string"},
            "must_keep_phrases": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["profile_id"],
    },
    cost="llm",
    side_effects="writes_db",
)
async def repurpose_caption(
    profile_id: int,
    platform: str = "x",
    post_id: int | None = None,
    source_text: str | None = None,
    must_keep_phrases: list[str] | None = None,
) -> dict:
    must_keep_phrases = _normalize_phrases(must_keep_phrases)

    async with session_scope() as session:
        post = None
        if post_id is not None:
            post = await session.get(Post, post_id)
            if post is None:
                return {"error": f"no post with id {post_id}"}
            source_text = post.caption
        elif not source_text:
            return {"error": "must provide either post_id or source_text"}

        voice_profile = (
            await session.exec(
                select(VoiceProfile).where(
                    VoiceProfile.profile_id == profile_id, VoiceProfile.is_current.is_(True)
                )
            )
        ).first()

        # The pipeline is DB-free (shared with POST /repurpose); the request row is
        # written after it returns, which also means an LLM failure leaves no
        # orphan request behind.
        outcome = await run_platform_repurpose(source_text, platform, voice_profile, must_keep_phrases)

        request = RepurposeRequest(
            profile_id=profile_id, source_caption=source_text, route_label=outcome.route_label
        )
        session.add(request)
        await session.commit()
        await session.refresh(request)

        attempt = None
        for record in outcome.attempts:
            attempt = RepurposeAttempt(
                request_id=request.id,
                platform=record.platform,
                tier=record.tier,
                model=record.model,
                provider=record.provider,
                attempt_no=record.attempt_no,
                output=record.output,
                must_keep_passed=record.must_keep_passed,
                judge_verdict=record.judge_verdict,
                judge_confidence=record.judge_confidence,
            )
            session.add(attempt)
        assert attempt is not None

        if post is not None and post.alerted_at is not None:
            post.alert_dismissed = True
            session.add(post)

        await session.commit()
        await session.refresh(attempt)

    return {
        "request_id": request.id,
        "attempt_id": attempt.id,
        "platform": platform,
        "route_label": outcome.route_label,
        "tier": outcome.tier,
        "model": outcome.model,
        "output": outcome.output,
        "changes": outcome.changes,
        "must_keep_passed": outcome.must_keep_passed,
        "feedback": outcome.feedback,
        "judge_verdict": outcome.judge_verdict,
        "judge_confidence": outcome.judge_confidence,
    }
