"""Profile bootstrap: auto-create voice profiles and peer frameworks in the background.

Flow:
0. Voice corpus: index the profile's posts into Chroma (derived, non-fatal) so
   extraction can later retrieve a diverse sample.
1. Voice profile: run extract_voice_profile for profiles missing a current voice
   profile. Retries until success (posts accumulate via PFM/Xpoz backfill).
2. Peer frameworks: once a voice profile exists, run the baseline-relative
   peer pipeline over the niche handles (Prompt 3 wiring) and persist the
   report — niche_framework_reports plus the peer_frameworks/Chroma bridge.
3. Own analysis: recompute the profile baseline (shared math with the peer
   pipeline), queue untagged posts as pending rows (blind tagging is stubbed
   until the peer extract lands), and refresh the own lift table. Local DB
   work only — no network or LLM calls.
"""

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlmodel import select

from app.agent.prompts import DEFAULT_NICHE_HANDLES
from app.database import session_scope
from app.models.frameworks import PeerFramework
from app.models.voice import VoiceProfile

log = logging.getLogger(__name__)

BOOTSTRAP_RETRY_SECONDS = 300  # retry voice extraction every ~5 min per profile
FRAMEWORK_REFRESH_DAYS = 7  # re-extract peer frameworks weekly
DEFAULT_NICHE_QUERY = "building in public AI startup founder"
PEER_WINNER_MIN_LIKES = 20

_last_attempt: dict[int, datetime] = {}
_tasks: set[asyncio.Task] = set()


def schedule_profile_bootstrap(profile_id: int) -> None:
    """Fire-and-forget bootstrap for a profile (safe to call from routers)."""
    task = asyncio.create_task(bootstrap_profile(profile_id))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def bootstrap_profile(profile_id: int, force: bool = False) -> dict[str, Any]:
    """Ensure a profile has a voice profile and peer frameworks.

    Skips if last attempt was < BOOTSTRAP_RETRY_SECONDS ago unless force=True.
    Never raises — errors are logged and returned in the result dict.
    """
    now = datetime.now(UTC)
    last = _last_attempt.get(profile_id)
    if not force and last and (now - last) < timedelta(seconds=BOOTSTRAP_RETRY_SECONDS):
        return {"skipped": True, "reason": "retry cooldown"}

    _last_attempt[profile_id] = now
    result: dict[str, Any] = {"profile_id": profile_id, "voice": None, "frameworks": None}

    try:
        result["corpus"] = await _sync_voice_corpus(profile_id)
        result["voice"] = await _ensure_voice_profile(profile_id)
        if await _has_current_voice_profile(profile_id):
            result["frameworks"] = await _ensure_peer_frameworks(profile_id)
        result["own_analysis"] = await _ensure_own_analysis(profile_id)
    except Exception as exc:  # noqa: BLE001
        log.warning("Bootstrap failed for profile %s: %s", profile_id, exc)
        result["error"] = str(exc)

    return result


async def _sync_voice_corpus(profile_id: int) -> dict[str, Any]:
    """Index the profile's posts into the Chroma voice_corpus (derived; non-fatal)."""
    from app.services.voice_corpus import sync_profile_corpus

    count = await sync_profile_corpus(profile_id)
    return {"status": "synced", "posts_indexed": count}


async def _has_current_voice_profile(profile_id: int) -> bool:
    async with session_scope() as session:
        row = (
            await session.exec(
                select(VoiceProfile).where(
                    VoiceProfile.profile_id == profile_id,
                    VoiceProfile.is_current.is_(True),
                )
            )
        ).first()
        return row is not None


async def _ensure_voice_profile(profile_id: int) -> dict[str, Any]:
    if await _has_current_voice_profile(profile_id):
        return {"status": "exists"}

    from app.tools.voice import extract_voice_profile

    out = await extract_voice_profile(profile_id)
    if out.get("needs_style_questions"):
        return {"status": "insufficient_posts", "reason": out.get("reason")}
    return {"status": "created", "version": out.get("version")}


async def _ensure_own_analysis(profile_id: int) -> dict[str, Any]:
    """Own-post analysis: profile baseline + blind-tagging queue + own lift.

    All local DB work (compute_own_lift is pure math over stored snapshots;
    tag_own_posts is a pending-row stub until Runtime Prompt A merges), so it
    is safe to run on every bootstrap tick.
    """
    from app.analysis.own_lift import compute_own_lift
    from app.analysis.own_tagging import tag_own_posts

    lift = await compute_own_lift(profile_id, persist_baseline=True)
    tagging = await tag_own_posts(profile_id)
    return {
        "lift_status": lift.get("status"),
        "baseline": lift.get("baseline"),
        "n_winners": lift.get("n_winners", 0),
        "tagging": tagging,
    }


async def _ensure_peer_frameworks(profile_id: int) -> dict[str, Any]:
    """Prompt 3: bootstrap runs the peer pipeline over the niche handles.

    Weekly refresh as before; the framework claims come from `run_peer_pipeline`
    (no canned fallback) and the result is bridged into `peer_frameworks` +
    Chroma so `get_peer_advice` keeps serving it from the store.
    """
    async with session_scope() as session:
        existing = (
            await session.exec(
                select(PeerFramework)
                .where(PeerFramework.profile_id == profile_id)
                .order_by(PeerFramework.created_at.desc())
            )
        ).first()

    # Weekly refresh: keep results fresh by re-extracting once the latest row ages out
    if existing is not None:
        try:
            age = datetime.now(UTC) - existing.created_at
            if age < timedelta(days=FRAMEWORK_REFRESH_DAYS):
                return {"status": "exists", "id": existing.id}
        except Exception as exc:  # noqa: BLE001
            log.debug("framework age check failed, refreshing: %s", exc)

    from app.services.peer_pipeline import (
        legacy_payload_from_report,
        run_peer_pipeline,
        winner_post_dicts,
    )
    from app.services.xpoz import XpozClient
    from app.tools.listening import check_niche_trends

    await check_niche_trends(profile_id, DEFAULT_NICHE_HANDLES, min_likes=PEER_WINNER_MIN_LIKES)

    client = XpozClient()
    try:
        run = await run_peer_pipeline(
            profile_id=profile_id,
            niche=DEFAULT_NICHE_QUERY,
            handles=list(DEFAULT_NICHE_HANDLES),
            client=client,
        )
    finally:
        await client.aclose()

    payload = legacy_payload_from_report(run.report, DEFAULT_NICHE_QUERY)
    payload["report_id"] = run.report_id

    async with session_scope() as session:
        row = PeerFramework(
            profile_id=profile_id,
            query=DEFAULT_NICHE_QUERY,
            niche_title=payload.get("niche_title", ""),
            payload=payload,
            analyzed_peers_count=payload.get("analyzed_peers_count", 0),
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)

    # Index into Chroma so get_peer_advice serves it instantly (non-fatal)
    from app.services.framework_corpus import upsert_framework, upsert_peer_posts

    upsert_framework(profile_id, row)
    upsert_peer_posts(profile_id, DEFAULT_NICHE_QUERY, winner_post_dicts(run))

    return {
        "status": "refreshed" if existing is not None else "created",
        "id": row.id,
        "winners_count": len(run.report.winner_post_ids),
        "report_status": run.report.status,
    }
