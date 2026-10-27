import asyncio
import logging
from datetime import UTC, datetime, timedelta

import neatlogs
from sqlmodel import select

from app.database import session_scope
from app.models.poll import PollConfig
from app.models.profile import Profile
from app.services.pfm import backfill_profile_posts
from app.tools.listening import check_trending

log = logging.getLogger(__name__)

TICK_SECONDS = 120  # drop to 30 for demos — see docs/background.md
DECAY_INTERVAL_DAYS = 7  # weekly memory decay sweep

_last_decay: datetime | None = None


@neatlogs.span(kind="WORKFLOW", name="poller_tick")
async def _poll_once() -> None:
    async with session_scope() as session:
        configs = (await session.exec(select(PollConfig).where(PollConfig.is_active.is_(True)))).all()

    now = datetime.now(UTC)
    due = [
        c
        for c in configs
        if c.last_polled_at is None or (now - c.last_polled_at).total_seconds() >= c.interval_minutes * 60
    ]

    for config in due:
        try:
            async with session_scope() as session:
                profile = await session.get(Profile, config.profile_id)
                if profile is not None and profile.pfm_account_id and not profile.pfm_account_id.startswith("demo-"):
                    await backfill_profile_posts(session, config.profile_id, profile.pfm_account_id)
        except Exception:  # noqa: BLE001
            log.warning("Metrics refresh failed for profile %s, continuing to spike check", config.profile_id)

        try:
            await check_trending(config.profile_id)
        except Exception:  # noqa: BLE001
            log.warning("Trending check failed for profile %s, continuing", config.profile_id)

    # Automatic retry-bootstrap-for-all-profiles-every-tick was removed: bootstrap_profile
    # (voice extraction + peer-framework scan) can hang long enough to fail the deploy
    # healthcheck and crash-loop the whole service. Bootstrap now only runs on-demand via
    # schedule_profile_bootstrap, fired once per profile from the PFM OAuth callback.
    await _decay_pass()


async def _decay_pass() -> None:
    """Weekly sweep: delete agent memories untouched for MEMORY_DECAY_DAYS."""
    global _last_decay
    now = datetime.now(UTC)
    if _last_decay is not None and (now - _last_decay) < timedelta(days=DECAY_INTERVAL_DAYS):
        return
    _last_decay = now
    try:
        from app.services.memory import MEMORY_DECAY_DAYS, decay_memories

        removed = decay_memories(MEMORY_DECAY_DAYS)
        if removed:
            log.info("memory decay removed %s stale entries", removed)
    except Exception:
        log.warning("memory decay pass failed, continuing", exc_info=True)


async def run_poller(stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        try:
            await _poll_once()
        except Exception:
            log.warning("Poller tick failed, will retry", exc_info=True)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=TICK_SECONDS)
        except TimeoutError:
            pass
