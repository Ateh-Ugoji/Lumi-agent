"""Tests for the shared repurpose pipeline, the POST /repurpose endpoint, and
the refactored repurpose_caption tool.

Everything runs against an in-memory SQLite schema with the LLM/Jev/TypeSafe
layers monkeypatched — no network, no real DB.
"""

from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI, HTTPException
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

import app.models  # noqa: F401  (registers all tables on SQLModel.metadata)
import app.routers.repurpose as repurpose_router
import app.tools.repurpose as repurpose_tool
from app.models.profile import Profile
from app.models.repurpose import RepurposeAttempt, RepurposeRequest
from app.models.voice import VoiceProfile
from app.routers.repurpose import RecaptionRequest, repurpose
from app.services import repurpose_flow
from app.services.enforcement import EnforcementResult
from app.services.repurpose_flow import (
    AttemptRecord,
    RepurposeOutcome,
    run_platform_repurpose,
)
from app.tools.repurpose import repurpose_caption


# ==========================================================================
# Fixtures
# ==========================================================================
@pytest.fixture
async def db(monkeypatch):
    """In-memory schema + session_scope patched into both callers + one profile."""
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    @asynccontextmanager
    async def fake_scope():
        async with factory() as session:
            yield session

    monkeypatch.setattr(repurpose_router, "session_scope", fake_scope)
    monkeypatch.setattr(repurpose_tool, "session_scope", fake_scope)

    async with factory() as session:
        session.add(Profile(name="Test", handle="ateh", pfm_account_id="spc_test_ateh"))
        await session.commit()

    yield factory
    await engine.dispose()


def _make_outcome(
    platform: str = "x",
    *,
    output: str = "rewritten caption",
    route_label: str = "standard",
    fallback: bool = False,
    must_keep_passed: bool = True,
) -> RepurposeOutcome:
    changes = [{"change": "restructured", "reason": "platform rule"}]
    if fallback:
        changes = [{"change": "Kept original text", "reason": "Fallback mode"}]
    return RepurposeOutcome(
        platform=platform,
        route_label=route_label,
        attempts=[
            AttemptRecord(
                attempt_no=1,
                platform=platform,
                tier="small",
                model="test-model",
                provider="groq",
                output=output,
                must_keep_passed=must_keep_passed,
                judge_verdict="yes",
                judge_confidence=0.9,
            )
        ],
        output=output,
        changes=changes,
        must_keep_passed=must_keep_passed,
        feedback=None,
        judge_verdict="yes",
        judge_confidence=0.9,
        tier="small",
        model="test-model",
    )


def _install_fake_core(monkeypatch, outcomes_by_platform: dict | None = None, default=None):
    """Record every platform the endpoint fans out and return canned outcomes."""
    calls: list[str] = []

    async def fake_run(source_text, platform, voice_profile=None, must_keep_phrases=None, route_label=None):
        calls.append(platform)
        if outcomes_by_platform is not None and platform in outcomes_by_platform:
            value = outcomes_by_platform[platform]
            if isinstance(value, Exception):
                raise value
            return value
        if default is not None:
            if isinstance(default, Exception):
                raise default
            return default
        return _make_outcome(platform)

    monkeypatch.setattr(repurpose_router, "run_platform_repurpose", fake_run)
    return calls


# ==========================================================================
# Endpoint — POST /repurpose
# ==========================================================================
async def test_happy_path_generates_and_persists_every_platform(db, monkeypatch):
    calls = _install_fake_core(monkeypatch)

    response = await repurpose(
        RecaptionRequest(source_text="we shipped the new builder tonight", platforms=["twitter", "linkedin"])
    )

    assert response.profile_id == 1
    assert len(response.results) == 2
    assert all(r.ok for r in response.results)
    assert {r.platform for r in response.results} == {"twitter", "linkedin"}
    assert all(r.output == "rewritten caption" for r in response.results)
    assert all(r.attempt_id is not None and r.request_id is not None for r in response.results)
    assert response.elapsed_ms >= 0
    # fan-out received the rule platforms (twitter aliases to x)
    assert sorted(calls) == ["linkedin", "x"]

    async with db() as session:
        requests = (await session.exec(select(RepurposeRequest))).all()
        attempts = (await session.exec(select(RepurposeAttempt))).all()
    assert len(requests) == 2
    assert len(attempts) == 2
    # route_label persisted from the outcome; attempt stores the requested target id
    assert {r.route_label for r in requests} == {"standard"}
    assert {a.platform for a in attempts} == {"twitter", "linkedin"}


async def test_aliases_map_frontend_platforms_to_rule_platforms(db, monkeypatch):
    calls = _install_fake_core(monkeypatch)

    response = await repurpose(
        RecaptionRequest(
            source_text="a build in public update",
            platforms=["bluesky", "facebook", "youtube", "farcaster", "twitter"],
        )
    )

    # what the pipeline actually received (rule sets)
    assert calls == ["x", "instagram", "linkedin", "x", "x"]
    by_platform = {r.platform: r for r in response.results}
    assert by_platform["bluesky"].rule_platform == "x"
    assert by_platform["facebook"].rule_platform == "instagram"
    assert by_platform["youtube"].rule_platform == "linkedin"
    assert by_platform["twitter"].rule_platform == "x"
    # client-facing ids stay untouched
    assert set(by_platform) == {"bluesky", "facebook", "youtube", "farcaster", "twitter"}


async def test_unknown_platform_is_rejected_before_any_generation(db, monkeypatch):
    calls = _install_fake_core(monkeypatch)

    with pytest.raises(HTTPException) as exc:
        await repurpose(RecaptionRequest(source_text="hello world", platforms=["myspace"]))

    assert exc.value.status_code == 422
    assert "myspace" in str(exc.value.detail)
    assert calls == []


async def test_blank_source_is_rejected(db, monkeypatch):
    calls = _install_fake_core(monkeypatch)

    with pytest.raises(HTTPException) as exc:
        await repurpose(RecaptionRequest(source_text="   ", platforms=["twitter"]))

    assert exc.value.status_code == 422
    assert calls == []


async def test_platforms_are_deduped_case_insensitively(db, monkeypatch):
    calls = _install_fake_core(monkeypatch)

    response = await repurpose(
        RecaptionRequest(source_text="same caption", platforms=["Twitter", " twitter ", "twitter"])
    )

    assert len(response.results) == 1
    assert calls == ["x"]


async def test_partial_failure_is_honest_and_only_successes_persist(db, monkeypatch):
    _install_fake_core(
        monkeypatch,
        outcomes_by_platform={"linkedin": RuntimeError("LLM blew up")},
        default=_make_outcome(),
    )

    response = await repurpose(
        RecaptionRequest(source_text="a caption worth rewriting", platforms=["twitter", "linkedin"])
    )

    by_platform = {r.platform: r for r in response.results}
    assert by_platform["twitter"].ok is True
    assert by_platform["twitter"].output == "rewritten caption"
    assert by_platform["linkedin"].ok is False
    assert by_platform["linkedin"].output is None
    assert "LLM blew up" in (by_platform["linkedin"].error or "")

    async with db() as session:
        attempts = (await session.exec(select(RepurposeAttempt))).all()
    assert len(attempts) == 1


async def test_generator_fallback_is_flagged_never_presented_as_generated(db, monkeypatch):
    _install_fake_core(monkeypatch, default=_make_outcome(fallback=True))

    response = await repurpose(RecaptionRequest(source_text="the source", platforms=["twitter"]))

    assert response.results[0].ok is True
    assert response.results[0].fallback is True
    assert response.results[0].output == "rewritten caption"


async def test_missing_profile_returns_404(db, monkeypatch):
    _install_fake_core(monkeypatch)
    async with db() as session:
        for row in (await session.exec(select(Profile))).all():
            await session.delete(row)
        await session.commit()

    with pytest.raises(HTTPException) as exc:
        await repurpose(RecaptionRequest(source_text="hello", platforms=["twitter"]))

    assert exc.value.status_code == 404


async def test_explicit_profile_id_selects_voice_and_profile(db, monkeypatch):
    _install_fake_core(monkeypatch)
    async with db() as session:
        other = Profile(name="Two", handle="second", pfm_account_id="spc_test_second")
        session.add(other)
        await session.commit()
        await session.refresh(other)

    response = await repurpose(
        RecaptionRequest(source_text="hello", platforms=["twitter"], profile_id=other.id)
    )

    assert response.profile_id == other.id


def test_max_platform_count_enforced_by_request_model():
    with pytest.raises(ValidationError):
        RecaptionRequest(source_text="x", platforms=["a"] * 9)


# ==========================================================================
# Endpoint via HTTP (no DB needed — validated before any session opens)
# ==========================================================================
def test_http_layer_maps_unknown_platform_to_422():
    app = FastAPI()
    app.include_router(repurpose_router.router)
    from fastapi.testclient import TestClient

    client = TestClient(app)
    res = client.post("/repurpose", json={"source_text": "hello", "platforms": ["spacebook"]})
    assert res.status_code == 422
    assert "spacebook" in res.json()["detail"]


# ==========================================================================
# Shared core — run_platform_repurpose
# ==========================================================================
async def test_core_runs_attempt_two_with_large_tier_on_enforcement_failure(monkeypatch):
    tiers: list[tuple[str, str | None]] = []
    feedbacks: list[str | None] = []

    async def fake_generate(source_text, platform, voice_profile=None, must_keep_phrases=None, tier="large", revision_feedback=None):
        tiers.append((tier, revision_feedback))
        feedbacks.append(revision_feedback)
        return {
            "platform": platform,
            "adapted_text": f"try {len(tiers)}",
            "changes": [],
            "tier": tier,
            "model": "m",
            "provider": "groq",
        }

    enforce_results = [
        EnforcementResult(must_keep_passed=False, feedback="missing required phrase(s): v2"),
        EnforcementResult(must_keep_passed=True, judge_verdict="yes", judge_confidence=0.9),
    ]

    async def fake_enforce(*args, **kwargs):
        return enforce_results.pop(0)

    monkeypatch.setattr(repurpose_flow, "classify_difficulty", _async_value("easy"))
    monkeypatch.setattr(repurpose_flow, "generate_platform_repurpose", fake_generate)
    monkeypatch.setattr(repurpose_flow, "enforce", fake_enforce)

    outcome = await run_platform_repurpose("source", "x", must_keep_phrases=["v2"])

    assert len(outcome.attempts) == 2
    # attempt 1 routed by difficulty (easy -> small), attempt 2 always large + retry feedback
    assert tiers[0] == ("small", None)
    assert tiers[1][0] == "large"
    assert "missing required phrase" in (feedbacks[1] or "")
    assert outcome.route_label == "easy"
    assert outcome.output == "try 2"
    assert outcome.must_keep_passed is True


async def test_core_stops_after_one_attempt_when_enforcement_passes(monkeypatch):
    async def fake_generate(**kwargs):
        return {
            "platform": kwargs.get("platform", "x"),
            "adapted_text": "good",
            "changes": [],
            "tier": "small",
            "model": "m",
            "provider": "groq",
        }

    async def fake_enforce(*args, **kwargs):
        return EnforcementResult(must_keep_passed=True, judge_verdict="yes", judge_confidence=0.95)

    monkeypatch.setattr(repurpose_flow, "classify_difficulty", _async_value("easy"))
    monkeypatch.setattr(repurpose_flow, "generate_platform_repurpose", fake_generate)
    monkeypatch.setattr(repurpose_flow, "enforce", fake_enforce)

    outcome = await run_platform_repurpose("source", "x")

    assert len(outcome.attempts) == 1
    assert outcome.output == "good"


def _async_value(value):
    """An async function that ignores its args and resolves to `value`."""
    async def _inner(*args, **kwargs):
        return value

    return _inner


# ==========================================================================
# Tool — repurpose_caption (return shape locked)
# ==========================================================================
TOOL_RETURN_KEYS = {
    "request_id",
    "attempt_id",
    "platform",
    "route_label",
    "tier",
    "model",
    "output",
    "changes",
    "must_keep_passed",
    "feedback",
    "judge_verdict",
    "judge_confidence",
}


async def test_tool_return_shape_and_persistence(db, monkeypatch):
    monkeypatch.setattr(
        repurpose_tool, "run_platform_repurpose", _async_value(_make_outcome("x"))
    )

    result = await repurpose_caption(profile_id=1, platform="x", source_text="the source caption")

    assert set(result) == TOOL_RETURN_KEYS
    assert result["platform"] == "x"
    assert result["route_label"] == "standard"
    assert result["output"] == "rewritten caption"
    assert result["attempt_id"] is not None and result["request_id"] is not None

    async with db() as session:
        requests = (await session.exec(select(RepurposeRequest))).all()
        attempts = (await session.exec(select(RepurposeAttempt))).all()
    assert len(requests) == 1 and requests[0].route_label == "standard"
    assert len(attempts) == 1 and attempts[0].platform == "x"


async def test_tool_errors_are_honest_strings(db, monkeypatch):
    monkeypatch.setattr(
        repurpose_tool, "run_platform_repurpose", _async_value(_make_outcome("x"))
    )

    no_source = await repurpose_caption(profile_id=1)
    assert "error" in no_source

    missing = await repurpose_caption(profile_id=1, post_id=999)
    assert "no post with id" in missing["error"]


async def test_tool_normalizes_json_string_must_keep_phrases(db, monkeypatch):
    seen: list[list[str]] = []

    async def fake_run(source_text, platform, voice_profile=None, must_keep_phrases=None, route_label=None):
        seen.append(must_keep_phrases or [])
        return _make_outcome("x")

    monkeypatch.setattr(repurpose_tool, "run_platform_repurpose", fake_run)

    await repurpose_caption(
        profile_id=1, source_text="hello", must_keep_phrases='["v2.0", "Oct 12"]'  # type: ignore[arg-type]
    )

    assert seen == [["v2.0", "Oct 12"]]


# ==========================================================================
# Voice profile threading
# ==========================================================================
async def test_voice_profile_is_loaded_and_passed_to_pipeline(db, monkeypatch):
    async with db() as session:
        session.add(
            VoiceProfile(
                profile_id=1,
                version=1,
                is_current=True,
                payload={"tone": "direct"},
            )
        )
        await session.commit()

    seen: list = []

    async def fake_run(source_text, platform, voice_profile=None, must_keep_phrases=None, route_label=None):
        seen.append(voice_profile)
        return _make_outcome(platform)

    monkeypatch.setattr(repurpose_router, "run_platform_repurpose", fake_run)

    await repurpose(RecaptionRequest(source_text="hello", platforms=["twitter"]))

    assert len(seen) == 1
    assert seen[0] is not None
    assert seen[0].payload["tone"] == "direct"
