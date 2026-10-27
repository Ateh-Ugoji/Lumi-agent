"""Persistence for the peer pipeline (Prompt 2).

Reports and taggings are *derived* data — they can be regenerated — so saving is
scoped and defensive: callers pass their own session, and parsing a stored row
that no longer matches the schema yields `None` instead of an exception. Failed
taggings are never reused from cache (the next run retries them); successful
ones are, keyed by `(post_id, prompt_version)`.
"""

from __future__ import annotations

import logging

from pydantic import ValidationError
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.peer_report import NicheFrameworkReportRow, PostTaggingRow
from app.schemas.peer import NicheFrameworkReport, PostAnalysis, PostTagging

log = logging.getLogger(__name__)


async def save_report(
    session: AsyncSession, profile_id: int, report: NicheFrameworkReport
) -> int | None:
    """Persist one report (full JSON contract) and return its row id."""
    row = NicheFrameworkReportRow(
        profile_id=profile_id,
        niche=report.niche,
        status=report.status,
        payload=report.model_dump(mode="json"),
        posts_analyzed=report.posts_analyzed,
        winner_count=len(report.winner_post_ids),
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row.id


async def latest_report(session: AsyncSession, profile_id: int) -> NicheFrameworkReport | None:
    """Newest report for a profile, or None (missing/legacy/corrupt payload)."""
    row = (
        await session.exec(
            select(NicheFrameworkReportRow)
            .where(NicheFrameworkReportRow.profile_id == profile_id)
            .order_by(NicheFrameworkReportRow.created_at.desc(), NicheFrameworkReportRow.id.desc())
            .limit(1)
        )
    ).first()
    if row is None or not row.payload:
        return None
    try:
        return NicheFrameworkReport(**row.payload)
    except ValidationError as exc:
        log.warning("stored niche framework report %s no longer parses: %s", row.id, exc)
        return None


async def save_taggings(session: AsyncSession, taggings: list[PostTagging]) -> int:
    """Upsert taggings by (post_id, prompt_version). Returns rows touched."""
    touched = 0
    for tagging in taggings:
        version = tagging.prompt_version or ""
        analysis = (
            tagging.analysis.model_dump(mode="json") if tagging.analysis is not None else None
        )
        fields = {
            "handle": tagging.handle,
            "status": tagging.status,
            "analysis": analysis,
            "framework_guess": tagging.framework_guess,
            "validation_error": tagging.validation_error,
            "tagged_at": tagging.tagged_at,
        }
        existing = (
            await session.exec(
                select(PostTaggingRow).where(
                    PostTaggingRow.post_id == tagging.post_id,
                    PostTaggingRow.prompt_version == version,
                )
            )
        ).first()
        if existing is None:
            session.add(PostTaggingRow(post_id=tagging.post_id, prompt_version=version, **fields))
        else:
            for key, value in fields.items():
                setattr(existing, key, value)
        touched += 1
    await session.commit()
    return touched


async def cached_taggings(
    session: AsyncSession, post_ids: list[str], prompt_version: str
) -> dict[str, PostTagging]:
    """Successful prior taggings for these posts under this prompt version.

    Failures are deliberately absent: they must be retried, not replayed.
    """
    if not post_ids:
        return {}
    rows = (
        await session.exec(
            select(PostTaggingRow).where(
                PostTaggingRow.post_id.in_(post_ids),
                PostTaggingRow.prompt_version == prompt_version,
                PostTaggingRow.status == "ok",
            )
        )
    ).all()

    out: dict[str, PostTagging] = {}
    for row in rows:
        if not row.analysis:
            continue
        try:
            out[row.post_id] = PostTagging(
                post_id=row.post_id,
                handle=row.handle,
                status="ok",
                analysis=PostAnalysis(**row.analysis),
                framework_guess=row.framework_guess,
                validation_error=row.validation_error,
                prompt_version=row.prompt_version,
                tagged_at=row.tagged_at,
            )
        except ValidationError as exc:
            log.warning("stored tagging for %s no longer parses: %s", row.post_id, exc)
    return out
