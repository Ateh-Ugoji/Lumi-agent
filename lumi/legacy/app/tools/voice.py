import logging

from sqlmodel import func, select

from app.database import session_scope
from app.models.activity import UserActivity
from app.models.post import Post
from app.models.profile import Profile
from app.models.voice import StyleAnswer, VoiceProfile
from app.services.pfm import backfill_profile_posts, is_authentic_original
from app.services.voice import extract_voice_from_captions
from app.tools.registry import tool

logger = logging.getLogger(__name__)

MIN_POSTS_FOR_EXTRACTION = 5
MAX_EXAMPLE_POSTS = 10
MAX_REPLY_SAMPLES = 10


async def _attempt_pfm_backfill(session, profile_id: int) -> list[Post]:
    """Attempt to fetch recent posts via Post for Me if local database is thin."""
    profile = await session.get(Profile, profile_id)
    if profile is None or not profile.pfm_account_id or profile.pfm_account_id.startswith("demo-"):
        return []

    try:
        await backfill_profile_posts(session, profile_id, profile.pfm_account_id)
    except Exception:
        logger.debug("PFM backfill attempt failed for profile %s", profile_id, exc_info=True)

    return (await session.exec(select(Post).where(Post.profile_id == profile_id))).all()


@tool(
    name="extract_voice_profile",
    description=(
        "Analyze a profile's recent posts to derive their writing voice. "
        "If there aren't enough posts to analyze, returns a `needs_style_questions` flag instead."
    ),
    parameters={
        "type": "object",
        "properties": {"profile_id": {"type": "integer"}},
        "required": ["profile_id"],
    },
    cost="llm",
    side_effects="writes_db",
)
async def extract_voice_profile(profile_id: int) -> dict:
    async with session_scope() as session:
        posts = (await session.exec(select(Post).where(Post.profile_id == profile_id))).all()

        if len(posts) < MIN_POSTS_FOR_EXTRACTION:
            # Try to backfill from Post for Me if available
            posts = await _attempt_pfm_backfill(session, profile_id)

        # Defense in depth: never feed retweets/replies into voice extraction,
        # even if older polluted rows are already in the DB.
        posts = [p for p in posts if is_authentic_original(p.caption)]

        if len(posts) < MIN_POSTS_FOR_EXTRACTION:
            return {
                "needs_style_questions": True,
                "reason": f"only {len(posts)} posts found, need at least {MIN_POSTS_FOR_EXTRACTION}",
            }

        # Index posts into the Chroma corpus (derived; failure is non-fatal)
        from app.services.voice_corpus import retrieve_extraction_sample, upsert_posts

        upsert_posts(profile_id, posts)

        # Load the prior current profile BEFORE extraction for version continuity
        current = (
            await session.exec(
                select(VoiceProfile).where(
                    VoiceProfile.profile_id == profile_id, VoiceProfile.is_current.is_(True)
                )
            )
        ).first()
        prior_payload = current.payload if current is not None else None
        prior_version = current.version if current is not None else None

        # Diverse sample from the corpus, falling back to the DB posts slice
        sample = retrieve_extraction_sample(profile_id, limit=MAX_EXAMPLE_POSTS)
        if sample:
            sample = [s for s in sample if is_authentic_original(s.get("caption"))] or None
        if sample:
            captions = [s["caption"] for s in sample]
            example_post_ids = [s["post_id"] for s in sample if s.get("post_id") is not None]
        else:
            example_posts = posts[:MAX_EXAMPLE_POSTS]
            captions = [p.caption for p in example_posts]
            example_post_ids = [p.id for p in example_posts]

        # Recent replies feed reply_style only — never the main voice fields
        reply_rows = (
            await session.exec(
                select(UserActivity)
                .where(UserActivity.profile_id == profile_id, UserActivity.kind == "reply")
                .order_by(UserActivity.published_at.desc())
                .limit(MAX_REPLY_SAMPLES)
            )
        ).all()
        reply_captions = [r.caption for r in reply_rows] or None

        payload = await extract_voice_from_captions(
            captions,
            prior_payload=prior_payload,
            prior_version=prior_version,
            reply_captions=reply_captions,
        )

        if current is not None:
            current.is_current = False
            session.add(current)
            await session.flush()

        latest_version = (
            await session.exec(select(func.max(VoiceProfile.version)).where(VoiceProfile.profile_id == profile_id))
        ).one()
        next_version = (latest_version or 0) + 1

        voice_profile = VoiceProfile(
            profile_id=profile_id,
            version=next_version,
            is_current=True,
            payload=payload,
            example_post_ids=example_post_ids,
        )
        session.add(voice_profile)
        await session.commit()
        await session.refresh(voice_profile)

        return {
            "needs_style_questions": False,
            "voice_profile_id": voice_profile.id,
            "version": next_version,
            "payload": payload,
        }


@tool(
    name="get_voice_profile",
    description="Fetch the current voice profile for a profile, if one exists.",
    parameters={
        "type": "object",
        "properties": {"profile_id": {"type": "integer"}},
        "required": ["profile_id"],
    },
    side_effects="none",
)
async def get_voice_profile(profile_id: int) -> dict:
    async with session_scope() as session:
        voice_profile = (
            await session.exec(
                select(VoiceProfile).where(
                    VoiceProfile.profile_id == profile_id, VoiceProfile.is_current.is_(True)
                )
            )
        ).first()

        if voice_profile is None:
            return {"found": False}

        return {
            "found": True,
            "version": voice_profile.version,
            "payload": voice_profile.payload,
            "example_post_ids": voice_profile.example_post_ids,
        }


@tool(
    name="answer_style_questions",
    description="Record the user's answers to style fallback questions when there isn't enough post history.",
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
    side_effects="writes_db",
)
async def answer_style_questions(profile_id: int, answers: list[dict]) -> dict:
    async with session_scope() as session:
        for item in answers:
            session.add(
                StyleAnswer(profile_id=profile_id, question_key=item["question_key"], answer=item["answer"])
            )
        await session.commit()

    return {"profile_id": profile_id, "recorded": len(answers)}
