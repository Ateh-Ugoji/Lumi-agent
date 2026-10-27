"""Background jobs of the AI side. Registered when the app starts (``apps.py``).

Both read the profile's own posts first through ``wiring.post_sync`` (CONNECT's
``DjangoOwnPostSync``: the connected account's feed into Postgres).

``profile.bootstrap`` prepares a new profile for the agent: it syncs the posts, indexes them for
retrieval and learns the voice. A profile with no connected account (or a feed that cannot be
read) is not an error here: it finishes with ``voice = needs_style_questions`` and the user
answers the style questions instead; the result says ``sync = unavailable``.

``profile.refresh`` (``POST /profiles/{id}/refresh``) is the same sync on demand plus the
re-index. The user asked for it, so a feed that cannot be read fails the job.
"""

from __future__ import annotations

import logging
from typing import Any

from asgiref.sync import async_to_sync

from apps.core import jobs
from apps.core.jobs import JobContext, JobError
from apps.profiles import services
from lumi_ai.ports import SocialDataError

log = logging.getLogger(__name__)

BOOTSTRAP_KIND = "profile.bootstrap"
REFRESH_KIND = "profile.refresh"
PROGRESS_SYNCED = 20
PROGRESS_INDEXED = 40
PROGRESS_VOICE = 90


@jobs.register(BOOTSTRAP_KIND)
def bootstrap_profile(ctx: JobContext) -> dict[str, Any]:
    if ctx.profile_id is None:
        raise JobError("validation_error", "El trabajo no trae un perfil.")
    from apps.intelligence.wiring import get_wiring

    wiring = get_wiring()
    profile_id = ctx.profile_id

    synced = _sync(wiring, profile_id)
    jobs.set_progress(ctx.id, PROGRESS_SYNCED)

    posts = async_to_sync(wiring.posts.list_posts)(
        profile_id, limit=wiring.config.voice_corpus_limit
    )
    indexed = wiring.indexer.index_posts(posts)
    jobs.set_progress(ctx.id, PROGRESS_INDEXED)

    refreshed = async_to_sync(wiring.style.ensure_voice)(profile_id)
    jobs.set_progress(ctx.id, PROGRESS_VOICE)
    if refreshed.status == "failed":
        log.warning(
            "voice bootstrap failed for profile %s: %s", profile_id, refreshed.reason
        )
        raise JobError(
            "voice_failed", "No se pudo aprender tu voz. Se puede reintentar más tarde."
        )

    services.mark_bootstrapped(profile_id)
    return {
        "sync": "ok" if synced is not None else "unavailable",
        "posts_synced": synced["stored"] if synced else 0,
        "posts_indexed": indexed,
        "voice": refreshed.status,
        "posts_found": refreshed.posts_found,
    }


@jobs.register(REFRESH_KIND)
def refresh_profile(ctx: JobContext) -> dict[str, Any]:
    if ctx.profile_id is None:
        raise JobError("validation_error", "El trabajo no trae un perfil.")
    from apps.intelligence.wiring import get_wiring

    wiring = get_wiring()
    synced = _sync(wiring, ctx.profile_id)
    if synced is None:
        raise JobError(
            "sync_failed",
            "No se pudieron leer tus publicaciones. Revisa que la cuenta siga conectada.",
        )
    jobs.set_progress(ctx.id, PROGRESS_SYNCED)

    posts = async_to_sync(wiring.posts.list_posts)(
        ctx.profile_id, limit=wiring.config.voice_corpus_limit
    )
    indexed = wiring.indexer.index_posts(posts)
    return {
        "posts_synced": synced["stored"],
        "posts_indexed": indexed,
        "complete": synced["complete"],
        "flagged_deleted": synced["flagged_deleted"],
    }


def _sync(wiring: Any, profile_id: int) -> dict[str, Any] | None:
    """Pull the connected account's posts. ``None`` when the feed could not be read."""
    try:
        return async_to_sync(wiring.post_sync.sync_own_posts)(profile_id)
    except SocialDataError as exc:
        log.warning(
            "own post sync failed for profile %s (%s): %s",
            profile_id,
            type(exc).__name__,
            exc,
        )
        return None
