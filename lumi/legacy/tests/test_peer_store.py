"""Prompt 2 persistence: report + tagging round-trip, upsert, and cache rules."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.peer_report import PostTaggingRow
from app.models.profile import Profile
from app.schemas.peer import NicheFrameworkReport, PostTagging
from app.services.peer_store import (
    cached_taggings,
    latest_report,
    save_report,
    save_taggings,
)

NOW = datetime(2026, 10, 26, 12, 0, tzinfo=UTC)


@pytest.fixture
async def db():
    """Per-test in-memory schema (tests only — Alembic owns the real schema)."""
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with factory() as session:
        session.add(Profile(name="T", handle="ateh", pfm_account_id="spc_test_peer_store"))
        await session.commit()

    yield factory
    await engine.dispose()


def _report(status: str = "ok") -> NicheFrameworkReport:
    return NicheFrameworkReport(
        niche="nigerian tech",
        generated_at=NOW,
        status=status,  # type: ignore[arg-type]
        accounts=[],
        winner_post_ids=["w1", "w2"],
        posts_analyzed=2,
        lift_table=[],
        synthesis=None,
    )


def _tagging(post_id: str, *, status: str = "ok", version: str = "peer-tag-v1") -> PostTagging:
    analysis = None
    if status == "ok":
        analysis = {
            "post_id": post_id,
            "hook": {
                "hook_text": "first line",
                "hook_type": "curiosity_gap",
                "modality": "text_only",
                "has_number": False,
                "has_named_entity": False,
                "open_loop": False,
                "specificity": 3,
                "tension": 3,
                "clarity": 3,
                "confidence": 0.9,
            },
            "body": {
                "primary_framework": "hot_take",
                "framework_confidence": 0.9,
                "specificity_score": 3,
                "open_loops": 0,
                "line_break_style": "short_paragraphs",
            },
            "cta": {"cta_type": "none", "placement": "none", "friction": "low"},
            "voice": {"pov": "first_person", "tone": ["direct"], "formality": 3, "humor": 0},
            "strategy": {
                "content_pillar": "build in public",
                "angle": "shipping",
                "intent": "educate",
                "funnel_stage": "awareness",
            },
        }
    return PostTagging(
        post_id=post_id,
        handle="a",
        status=status,  # type: ignore[arg-type]
        analysis=analysis,  # type: ignore[arg-type]
        prompt_version=version,
        tagged_at=NOW,
        validation_error=None if status == "ok" else "llm_call_failed: boom",
    )


# ---------------------------------------------------------------- reports
async def test_report_round_trip(db) -> None:
    async with db() as session:
        row_id = await save_report(session, 1, _report())
        assert row_id is not None
        loaded = await latest_report(session, 1)
    assert loaded is not None
    assert loaded.niche == "nigerian tech"
    assert loaded.status == "ok"
    assert loaded.winner_post_ids == ["w1", "w2"]
    assert loaded.generated_at == NOW


async def test_latest_report_is_none_when_nothing_saved(db) -> None:
    async with db() as session:
        assert await latest_report(session, 42) is None


async def test_status_is_stored_for_querying(db) -> None:
    from app.models.peer_report import NicheFrameworkReportRow

    async with db() as session:
        await save_report(session, 1, _report(status="insufficient_data"))
        rows = (await session.exec(select(NicheFrameworkReportRow))).all()
        assert [r.status for r in rows] == ["insufficient_data"]
        stored = await latest_report(session, 1)
    assert stored is not None and stored.status == "insufficient_data"


# ---------------------------------------------------------------- taggings
async def test_tagging_upsert_is_idempotent_per_prompt_version(db) -> None:
    async with db() as session:
        await save_taggings(session, [_tagging("p1")])
        await save_taggings(session, [_tagging("p1", status="failed")])
        rows = (await session.exec(select(PostTaggingRow))).all()
        assert len(rows) == 1, "same post + prompt version must not duplicate"
        assert rows[0].status == "failed"
        assert rows[0].analysis is None, "a failed row never stores an analysis"


async def test_cache_only_returns_successful_current_prompt_rows(db) -> None:
    async with db() as session:
        await save_taggings(
            session,
            [
                _tagging("ok_post"),
                _tagging("failed_post", status="failed"),
                _tagging("old_prompt_post", version="peer-tag-v0"),
            ],
        )
        cached = await cached_taggings(session, ["ok_post", "failed_post", "old_prompt_post"], "peer-tag-v1")

    assert sorted(cached) == ["ok_post"]
    assert cached["ok_post"].analysis is not None
    assert cached["ok_post"].analysis.body.primary_framework == "hot_take"


async def test_cache_is_scoped_to_the_requested_posts(db) -> None:
    async with db() as session:
        await save_taggings(session, [_tagging("p1")])
        assert await cached_taggings(session, ["other"], "peer-tag-v1") == {}
        assert await cached_taggings(session, [], "peer-tag-v1") == {}


async def test_a_prompt_bump_retags_everything(db) -> None:
    async with db() as session:
        await save_taggings(session, [_tagging("p1", version="peer-tag-v1")])
        assert await cached_taggings(session, ["p1"], "peer-tag-v2") == {}
        assert await cached_taggings(session, ["p1"], "peer-tag-v1") != {}
