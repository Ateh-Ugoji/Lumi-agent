"""AI recaption REST endpoint for external clients (webapp composer).

`POST /repurpose` runs the same pipeline as the `repurpose_caption` agent tool
(`app/services/repurpose_flow.py`), fanned out across the requested platforms
concurrently — the pipeline is DB-free, so only two short sessions are used:
one read (profile + current voice profile) and one write (all requests +
attempts, single commit).

No auth: same demo posture as every other route here (CORS is wide open).
"""

import asyncio
import logging
import time

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import select

from app.database import session_scope
from app.models.profile import Profile
from app.models.repurpose import RepurposeAttempt, RepurposeRequest
from app.models.voice import VoiceProfile
from app.services.repurpose_flow import run_platform_repurpose

log = logging.getLogger(__name__)
router = APIRouter()

# Frontend platform id -> the rule set applied (PLATFORM_RULES /
# platform_char_limit keys). Platforms without their own rules borrow the
# closest one: short-form feeds -> X, narrative feeds -> Instagram,
# long-form feeds -> LinkedIn. The response always reports both ids.
PLATFORM_ALIASES: dict[str, str] = {
    "twitter": "x",
    "x": "x",
    "linkedin": "linkedin",
    "tiktok": "tiktok",
    "instagram": "instagram",
    "bluesky": "x",
    "farcaster": "x",
    "facebook": "instagram",
    "youtube": "linkedin",
}


class RecaptionRequest(BaseModel):
    source_text: str = Field(min_length=1, max_length=8000)
    platforms: list[str] = Field(min_length=1, max_length=8)
    profile_id: int | None = None
    must_keep_phrases: list[str] = Field(default_factory=list, max_length=20)


class RecaptionResult(BaseModel):
    platform: str  # as requested by the client (frontend id)
    rule_platform: str  # rule set actually applied
    ok: bool
    attempt_id: int | None = None
    request_id: int | None = None
    output: str | None = None
    changes: list[dict] = Field(default_factory=list)
    must_keep_passed: bool | None = None
    judge_verdict: str | None = None
    judge_confidence: float | None = None
    route_label: str | None = None
    # Generator returned the source unchanged (LLM outage passthrough) — never
    # present this as a generated recaption.
    fallback: bool = False
    error: str | None = None


class RecaptionResponse(BaseModel):
    profile_id: int
    results: list[RecaptionResult]
    elapsed_ms: int


@router.post("/repurpose", response_model=RecaptionResponse)
async def repurpose(request: RecaptionRequest) -> RecaptionResponse:
    source_text = request.source_text.strip()
    if not source_text:
        raise HTTPException(status_code=422, detail="source_text is empty")

    # Normalize + dedupe while preserving order; anything unknown is rejected
    # loudly (an unaliased id would silently fall through to X rules).
    platforms: list[str] = []
    for raw in request.platforms:
        key = raw.strip().lower()
        if key not in PLATFORM_ALIASES:
            raise HTTPException(
                status_code=422,
                detail=f"unsupported platform: {raw!r}; supported: {sorted(set(PLATFORM_ALIASES))}",
            )
        if key not in platforms:
            platforms.append(key)

    must_keep = [p for p in (s.strip() for s in request.must_keep_phrases) if p]

    async with session_scope() as session:
        if request.profile_id is not None:
            profile = await session.get(Profile, request.profile_id)
        else:
            profile = (await session.exec(select(Profile).order_by(Profile.id))).first()
        if profile is None:
            raise HTTPException(status_code=404, detail="no profile available for repurposing")
        voice_profile = (
            await session.exec(
                select(VoiceProfile).where(
                    VoiceProfile.profile_id == profile.id, VoiceProfile.is_current.is_(True)
                )
            )
        ).first()
        profile_id = profile.id

    started = time.monotonic()
    # Pure LLM fan-out: no sessions, no locks. Order matches `platforms`.
    outcomes = await asyncio.gather(
        *(
            run_platform_repurpose(source_text, PLATFORM_ALIASES[platform], voice_profile, must_keep)
            for platform in platforms
        ),
        return_exceptions=True,
    )

    results: list[RecaptionResult] = []
    async with session_scope() as session:
        for platform, outcome in zip(platforms, outcomes, strict=True):
            rule_platform = PLATFORM_ALIASES[platform]
            if isinstance(outcome, BaseException):
                log.warning("repurpose failed for %s: %s", platform, outcome)
                results.append(
                    RecaptionResult(
                        platform=platform, rule_platform=rule_platform, ok=False, error=str(outcome)
                    )
                )
                continue
            # One request row per platform (route_label can differ per target),
            # all attempts flushed, ONE commit for the whole batch.
            row_request = RepurposeRequest(
                profile_id=profile_id, source_caption=source_text, route_label=outcome.route_label
            )
            session.add(row_request)
            await session.flush()
            attempt_id = None
            for record in outcome.attempts:
                row_attempt = RepurposeAttempt(
                    request_id=row_request.id,
                    platform=platform,
                    tier=record.tier,
                    model=record.model,
                    provider=record.provider,
                    attempt_no=record.attempt_no,
                    output=record.output,
                    must_keep_passed=record.must_keep_passed,
                    judge_verdict=record.judge_verdict,
                    judge_confidence=record.judge_confidence,
                )
                session.add(row_attempt)
                await session.flush()
                attempt_id = row_attempt.id
            results.append(
                RecaptionResult(
                    platform=platform,
                    rule_platform=rule_platform,
                    ok=True,
                    attempt_id=attempt_id,
                    request_id=row_request.id,
                    output=outcome.output,
                    changes=outcome.changes,
                    must_keep_passed=outcome.must_keep_passed,
                    judge_verdict=outcome.judge_verdict,
                    judge_confidence=outcome.judge_confidence,
                    route_label=outcome.route_label,
                    fallback=outcome.fell_back,
                )
            )
        await session.commit()

    return RecaptionResponse(
        profile_id=profile_id,
        results=results,
        elapsed_ms=int((time.monotonic() - started) * 1000),
    )
