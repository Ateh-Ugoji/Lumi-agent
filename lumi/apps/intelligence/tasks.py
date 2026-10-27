"""Background jobs of the AI side. Registered when the app starts (``apps.py``).

``profile.bootstrap`` prepares a new profile for the agent: it indexes the user's own posts for
retrieval and learns the voice. It does not fetch posts: reading the connected account is
CONNECT's ``OwnPostSync`` (not wired yet), so a profile with no stored posts finishes with
``voice = needs_style_questions`` and the user answers the style questions instead.
"""

from __future__ import annotations

import logging
from typing import Any

from asgiref.sync import async_to_sync

from apps.core import jobs
from apps.core.jobs import JobContext, JobError
from apps.profiles import services

log = logging.getLogger(__name__)

BOOTSTRAP_KIND = "profile.bootstrap"
PROGRESS_INDEXED = 40
PROGRESS_VOICE = 90


@jobs.register(BOOTSTRAP_KIND)
def bootstrap_profile(ctx: JobContext) -> dict[str, Any]:
    if ctx.profile_id is None:
        raise JobError("validation_error", "El trabajo no trae un perfil.")
    from apps.intelligence.wiring import get_wiring

    wiring = get_wiring()
    profile_id = ctx.profile_id

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
        "posts_indexed": indexed,
        "voice": refreshed.status,
        "posts_found": refreshed.posts_found,
    }
