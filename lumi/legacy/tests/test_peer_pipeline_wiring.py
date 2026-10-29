"""Prompt 3 wiring: the peer pipeline is what actually runs.

- `run_peer_pipeline` end to end against a fake Xpoz client: per-account fetch,
  per-account winner bar, report + taggings persisted, prior taggings reused on
  re-run, and a synthesis that names no frameworks when nothing lifts.
- bootstrap's `_ensure_peer_frameworks` runs *this* pipeline and bridges the
  report into `peer_frameworks` (the tool call site is covered by
  `tests/test_xpoz_resilience.py` + `tests/test_handle_db.py`).
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession
from test_peer_synthesize import _tagging  # shared PostAnalysis/PostTagging builders

from app.models.peer_report import NicheFrameworkReportRow, PostTaggingRow
from app.models.profile import Profile
from app.schemas.peer import NicheFrameworkReport
from app.services import peer_pipeline
from app.services.peer_pipeline import run_peer_pipeline

NOW = datetime.now(UTC)


def _live_posts(handle: str, *, views: int) -> list[dict]:
    """32 posts for one account, one every 20h (all inside the 28-day window)."""
    return [
        {
            "id": f"{handle}-{i}",
            "text": f"post {i} from {handle}",
            "authorUsername": handle,
            "impressionCount": views,
            "createdAt": (NOW - timedelta(hours=20 * (i + 1))).isoformat(),
        }
        for i in range(32)
    ]


class FakeXpoz:
    """Real 20-post pages with a cursor, like the live endpoint."""

    def __init__(self, accounts: dict[str, list[dict]]):
        self._accounts = accounts
        self.page_calls = 0

    async def get_user_live_posts_page(self, username, *, limit=20, cursor=None):
        self.page_calls += 1
        posts = self._accounts.get(username.lstrip("@"), [])
        start = int(cursor or 0)
        end = min(start + 20, len(posts))
        nxt = end if end < len(posts) else None
        return posts[start:end], (str(nxt) if nxt is not None else None), nxt is not None

    async def aclose(self):
        pass


@pytest.fixture
async def db(monkeypatch):
    """In-memory schema behind `app.database.session_scope` (the pipeline's session)."""
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    @asynccontextmanager
    async def scope():
        async with factory() as session:
            yield session

    monkeypatch.setattr("app.database.session_scope", scope)

    async with factory() as session:
        session.add(Profile(name="T", handle="ateh", pfm_account_id="spc_test_pip"))
        await session.commit()

    yield factory
    await engine.dispose()


async def test_pipeline_end_to_end_picks_per_account_winners_and_persists(db, monkeypatch):
    # Two small-ish accounts: 24 quiet posts at 100 views + 8 breakouts at 1000.
    # The bar is each account's OWN median (100), so all 8 break out at 10x —
    # capped at MAX_WINNERS_PER_ACCOUNT=5 each.
    accounts = {
        handle: _live_posts(handle, views=100)[:24] + _live_posts(handle, views=1000)[24:32]
        for handle in ("peer_one", "peer_two")
    }
    client = FakeXpoz(accounts)

    tagged = {"posts": 0}

    async def fake_tag(posts):
        tagged["posts"] += len(posts)
        # "listicle" carries no required detail block (see BodyAnalysis's validator).
        return [_tagging(m.post_id, "listicle", 0.9) for m in posts]

    monkeypatch.setattr("app.services.peer_pipeline.tag_posts", fake_tag)

    run = await run_peer_pipeline(
        profile_id=1, niche="tech founders", handles=list(accounts), client=client
    )

    assert run.scanned == {"peer_one": 32, "peer_two": 32}
    assert run.report.status == "ok", "10 winners >= MIN_WINNERS_FOR_REPORT=8"
    assert len(run.report.winner_post_ids) == 10, "5 per account — the per-account cap"
    assert all(w.startswith(("peer_one-", "peer_two-")) for w in run.report.winner_post_ids)
    assert tagged["posts"] == 64, "every buildable post is blind-tagged"
    # Both accounts use the same structure everywhere -> nothing lifts -> the
    # synthesis reports no frameworks (a warning instead of a guess).
    assert run.report.synthesis is not None
    assert run.report.synthesis.winning_frameworks == []

    async with db() as session:
        reports = (await session.exec(select(NicheFrameworkReportRow))).all()
        rows = (await session.exec(select(PostTaggingRow))).all()
    assert [r.status for r in reports] == ["ok"]
    assert reports[0].winner_count == 10
    assert len(rows) == 64, "one tagging row per post, keyed (post_id, prompt_version)"

    # Re-run: the LLM stage must not re-tag posts already cached under this
    # prompt version (Prompt 2's dedup rule).
    run2 = await run_peer_pipeline(
        profile_id=1, niche="tech founders", handles=list(accounts), client=client
    )
    assert tagged["posts"] == 64, "second run reused all 64 cached taggings"
    assert run2.report.winner_post_ids == run.report.winner_post_ids, "pure code — deterministic"

    async with db() as session:
        reports = (await session.exec(select(NicheFrameworkReportRow))).all()
    assert len(reports) == 2, "each run stores its own report"


async def test_bootstrap_ensure_peer_frameworks_runs_the_pipeline(monkeypatch):
    from app.background import bootstrap
    from app.models.frameworks import PeerFramework

    added: list[PeerFramework] = []
    ran: dict = {}

    class _Scalar:
        def first(self):
            return None  # no existing row -> bootstrap refreshes

    class _FakeSession:
        async def exec(self, _stmt):
            return _Scalar()

        def add(self, row):
            added.append(row)

        async def commit(self):
            pass

        async def refresh(self, row):
            row.id = row.id or 42

    @asynccontextmanager
    async def scope():
        yield _FakeSession()

    async def fake_trends(*_args, **_kwargs):
        return {"new_matches_found": 0}

    class FakeXpoz:
        async def aclose(self):
            pass

    report = NicheFrameworkReport(
        niche=bootstrap.DEFAULT_NICHE_QUERY,
        generated_at=NOW,
        status="insufficient_data",
        accounts=[],
        winner_post_ids=[],
        posts_analyzed=0,
        lift_table=[],
        synthesis=None,
    )

    async def fake_pipeline(**kwargs):
        ran.update(kwargs)
        return peer_pipeline.PipelineResult(report=report, taggings=[])

    monkeypatch.setattr(bootstrap, "session_scope", scope)
    monkeypatch.setattr("app.tools.listening.check_niche_trends", fake_trends)
    monkeypatch.setattr("app.services.xpoz.XpozClient", FakeXpoz)
    monkeypatch.setattr("app.services.peer_pipeline.run_peer_pipeline", fake_pipeline)
    monkeypatch.setattr(
        "app.services.framework_corpus.upsert_framework", lambda *_a, **_k: False
    )
    monkeypatch.setattr("app.services.framework_corpus.upsert_peer_posts", lambda *_a, **_k: 0)

    out = await bootstrap._ensure_peer_frameworks(1)

    assert ran["niche"] == bootstrap.DEFAULT_NICHE_QUERY
    assert ran["handles"] == list(bootstrap.DEFAULT_NICHE_HANDLES)
    assert added, "the bridged peer_frameworks row is still written"
    assert added[0].payload["report_status"] == "insufficient_data"
    assert added[0].payload["winning_frameworks"] == [], "no canned frameworks ever"
    assert added[0].payload["niche_title"] == bootstrap.DEFAULT_NICHE_QUERY
    assert out["report_status"] == "insufficient_data"
    assert out["winners_count"] == 0
    assert out["status"] in {"created", "refreshed"}
