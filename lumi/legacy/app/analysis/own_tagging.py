"""Blind tagging of the user's own posts into own_post_analysis.

STUB: the peer extract that owns Runtime Prompt A (opencode_prompts.md
Prompt 2) is NOT merged yet (app/analysis/extract.py does not exist), so no
LLM call is made here. What this does instead:

- queues eligible posts as status="pending" rows (no analysis invented);
- never writes an analysis payload, never calls a prompt.

When the peer pipeline lands, replace `_run_llm_tagging` with the SAME
PostAnalysisBatch prompt + schema used for peers, keeping the
(post_id, prompt_version) caching rule — profile_extract_fixes.md Step 3.
"""

from __future__ import annotations

import logging

from sqlmodel import select

from app.database import session_scope
from app.models.analysis import OwnPostAnalysis
from app.models.post import Post

log = logging.getLogger(__name__)

STUB_REASON = "peer extract (Runtime Prompt A) not merged yet — queued as pending"


async def tag_own_posts(profile_id: int) -> dict:
    """Queue untagged eligible posts as pending. Returns a status dict."""
    async with session_scope() as session:
        posts = (await session.exec(select(Post).where(Post.profile_id == profile_id))).all()
        queued_ids = set(
            (await session.exec(select(OwnPostAnalysis.post_id))).all()
        )

        queued = 0
        for post in posts:
            if post.id is None or post.id in queued_ids:
                continue
            if post.text_truncated:
                continue  # flagged text is excluded from hook/body analysis
            session.add(OwnPostAnalysis(post_id=post.id, status="pending"))
            queued += 1
        await session.commit()

    log.info("own tagging stub for profile %s: queued %d pending rows", profile_id, queued)
    return {
        "status": "stub",
        "reason": STUB_REASON,
        "queued": queued,
    }
