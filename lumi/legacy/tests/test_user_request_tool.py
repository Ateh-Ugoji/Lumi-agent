"""save_user_request: pasted handles become USER REQUESTS, never peers.

Covers handle normalization/validation, peer-set membership reporting, the
append-only already_requested flag, and the hard guarantee that saving a user
request never writes to the peer stores (peer_frameworks / listening_matches).
"""

from contextlib import asynccontextmanager

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.frameworks import PeerFramework
from app.models.listening import ListeningMatch
from app.models.profile import Profile
from app.models.user_request import UserSearchRequest
from app.tools import registry, user_requests
from app.tools.user_requests import _normalize_handle, save_user_request


@pytest.fixture
async def db(monkeypatch):
    """In-memory schema + app.tools.user_requests.session_scope patched to it."""
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

    monkeypatch.setattr(user_requests, "session_scope", scope)

    async with factory() as session:
        session.add(Profile(name="T", handle="ateh", pfm_account_id="spc_test_ur"))
        await session.commit()

    yield factory
    await engine.dispose()


def test_tool_is_registered_with_the_registry():
    specs = {s["function"]["name"] for s in registry.list_tool_specs()}
    assert "save_user_request" in specs


def test_normalize_handle_accepts_valid_and_rejects_garbage():
    assert _normalize_handle("@Beaconsai") == "beaconsai"
    assert _normalize_handle(" wabi,") == "wabi"
    assert _normalize_handle("@levelsio") == "levelsio"
    assert _normalize_handle("beacons.ai") == ""  # dots are not valid X handles
    assert _normalize_handle("people like @wabi") == ""
    assert _normalize_handle(None) == ""


async def test_saves_normalized_handles_and_reports_invalid(db):
    result = await save_user_request(
        1, ["@Beaconsai,", "wabi", "beacons.ai"], request="find their peers"
    )

    assert [s["handle"] for s in result["saved"]] == ["beaconsai", "wabi"]
    assert result["invalid"] == ["beacons.ai"]
    assert result["note"] == "find their peers"
    assert all(s["in_peer_set"] is False for s in result["saved"])

    async with db() as session:
        rows = (await session.exec(select(UserSearchRequest))).all()
    assert [(r.handle, r.request_note) for r in rows] == [
        ("beaconsai", "find their peers"),
        ("wabi", "find their peers"),
    ]


async def test_membership_flags_handles_already_in_peer_set(db):
    async with db() as session:
        session.add(
            PeerFramework(
                profile_id=1,
                query="x",
                payload={"top_peer_handles": ["@beaconsai"]},
            )
        )
        session.add(
            ListeningMatch(
                profile_id=1,
                platform_post_id="p1",
                author_handle="wabi",
                caption="hello",
                platform_url="https://x.com/wabi/status/1",
            )
        )
        await session.commit()

    result = await save_user_request(1, ["sama", "beaconsai", "wabi", "stranger"])

    by_handle = {s["handle"]: s for s in result["saved"]}
    assert by_handle["sama"]["in_peer_set"] is True
    assert by_handle["sama"]["peer_source"] == "niche_default"
    assert by_handle["beaconsai"]["peer_source"] == "peer_frameworks"
    assert by_handle["wabi"]["peer_source"] == "listening_matches"
    assert by_handle["stranger"]["in_peer_set"] is False


async def test_re_requests_are_append_only_and_flagged(db):
    await save_user_request(1, ["beaconsai"])
    second = await save_user_request(1, ["@Beaconsai"], request="again")

    assert second["saved"][0]["already_requested"] is True
    async with db() as session:
        rows = (await session.exec(select(UserSearchRequest))).all()
    assert len(rows) == 2  # append-only log, no overwrite


async def test_saving_never_writes_the_peer_stores(db):
    await save_user_request(1, ["beaconsai", "wabi"], request="their peers recon")

    async with db() as session:
        frameworks = (await session.exec(select(PeerFramework))).all()
        matches = (await session.exec(select(ListeningMatch))).all()
    assert frameworks == []
    assert matches == []
