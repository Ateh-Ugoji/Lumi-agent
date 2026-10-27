"""The runtime seam, the voice reader and the ``profile.bootstrap`` job.

``get_wiring`` is the real one in the first class (no keys: the honest "not configured" paths);
the bootstrap tests swap in a small stand-in for the indexer and the style service only.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from asgiref.sync import async_to_sync

from apps.connections import mcp_gateway
from apps.core import jobs
from apps.core.errors import ApiError
from apps.core.jobs import JobError
from apps.intelligence import runtime, tasks, wiring
from apps.intelligence.repos import PostRepo, VoiceRepo
from apps.profiles import hooks, services
from apps.profiles.models import SocialProfile
from lumi_ai import ports
from lumi_ai.config import ENV_FIELDS, AIConfig
from lumi_ai.style.service import VoiceRefresh


@pytest.fixture
def no_keys(monkeypatch, tmp_path):
    for name in ENV_FIELDS:
        if name.endswith("api_key"):
            monkeypatch.delenv(name.upper(), raising=False)
    monkeypatch.setenv("CHROMA_PATH", str(tmp_path / "chroma"))
    wiring.get_wiring.cache_clear()
    yield
    wiring.get_wiring.cache_clear()


class TestRuntimeWithoutKeys:
    def test_the_registry_has_the_tools_that_need_nothing_from_connect(self, no_keys):
        names = set(wiring.get_wiring().registry.names)
        assert {"get_posts", "check_niche_trends"} <= names
        assert "publish_post" not in names  # nobody wired a publishing tool
        assert "connect_account" in names  # CONNECT's DjangoConnectionLinks is wired
        assert "backfill_posts" not in names  # OwnPostSync is not delivered yet

    def test_a_chat_turn_says_the_model_is_not_configured(self, no_keys, profile):
        with pytest.raises(ApiError) as caught:
            async_to_sync(runtime.run_turn)(profile.pk, "hello")
        assert caught.value.api_code == "llm_not_configured"
        assert caught.value.status_code == 503

    def test_a_stream_ends_with_a_coded_error_event(self, no_keys, profile):
        async def collect():
            return [e async for e in runtime.stream_turn(profile.pk, "hello")]

        events = async_to_sync(collect)()
        assert events[-1].type == "error"
        assert events[-1].data["code"] == "llm_not_configured"

    def test_a_title_is_none_when_no_model_is_there_to_write_one(self, no_keys):
        assert async_to_sync(runtime.generate_title)("hello") is None


class RecordingGateway:
    """CONNECT's McpGateway port, recording what the loop asks of it."""

    def __init__(self):
        self.resolved = []

    async def list_tools(self, profile_id):
        return []

    async def call(
        self, profile_id, name, args
    ):  # pragma: no cover - no model, no tool call
        raise AssertionError("no tool should run without a model")

    async def resolve_pending(self, profile_id, user_message):
        self.resolved.append((profile_id, user_message))


class TestMcpGateway:
    def test_the_gateway_is_injected_and_asked_before_every_turn(
        self, no_keys, profile, monkeypatch
    ):
        gateway = RecordingGateway()
        monkeypatch.setattr(mcp_gateway, "build_mcp_gateway", lambda: gateway)
        wiring.get_wiring.cache_clear()
        assert wiring.get_wiring().loop.deps.mcp is gateway
        with pytest.raises(
            ApiError
        ):  # no model keys: the turn stops, but only after the gateway
            async_to_sync(runtime.run_turn)(profile.pk, "yes, go ahead")
        assert gateway.resolved == [(profile.pk, "yes, go ahead")]

    def test_the_real_gateway_builds_without_keys(self, no_keys):
        assert wiring.get_wiring().loop.deps.mcp is not None


class TestVoiceReader:
    def test_the_profiles_hook_sees_which_profiles_have_a_voice(self, profile):
        assert hooks.voice_profile_reader([profile.pk]) == set()
        async_to_sync(VoiceRepo().save_voice)(profile.pk, None, {"a": 1}, "posts", [])
        assert hooks.voice_profile_reader([profile.pk, 0]) == {profile.pk}


class Style:
    def __init__(self, outcome):
        self.outcome = outcome
        self.calls = []

    async def ensure_voice(self, profile_id):
        self.calls.append(profile_id)
        return self.outcome


class Indexer:
    def __init__(self):
        self.seen = []

    def index_posts(self, posts):
        self.seen.extend(posts)
        return len(posts)


@pytest.fixture
def bootstrap(monkeypatch):
    def arrange(outcome):
        style, indexer = Style(outcome), Indexer()
        monkeypatch.setattr(
            wiring,
            "get_wiring",
            lambda: SimpleNamespace(
                posts=PostRepo(), config=AIConfig(), style=style, indexer=indexer
            ),
        )
        return style, indexer

    return arrange


def ctx(profile):
    import uuid

    return jobs.JobContext(
        uuid.uuid4(), profile.user_id, profile.pk, tasks.BOOTSTRAP_KIND, {}
    )


class TestBootstrapJob:
    @pytest.fixture(autouse=True)
    def _progress(self, monkeypatch):
        self.progress = []
        monkeypatch.setattr(
            jobs, "set_progress", lambda _id, pct: self.progress.append(pct)
        )

    def test_it_is_registered_for_the_kind_the_profiles_app_enqueues(self):
        assert tasks.BOOTSTRAP_KIND == "profile.bootstrap"
        assert jobs._HANDLERS[tasks.BOOTSTRAP_KIND] is tasks.bootstrap_profile

    def test_it_indexes_the_posts_learns_the_voice_and_marks_the_profile(
        self, profile, bootstrap
    ):
        services.upsert_posts(
            profile.handle_id,
            [ports.PostIn("x", "p1", "first post", datetime(2026, 9, 1, tzinfo=UTC))],
        )
        style, indexer = bootstrap(VoiceRefresh("created", posts_found=1))
        out = tasks.bootstrap_profile(ctx(profile))
        assert out == {"posts_indexed": 1, "voice": "created", "posts_found": 1}
        assert style.calls == [profile.pk] and len(indexer.seen) == 1
        assert self.progress == [tasks.PROGRESS_INDEXED, tasks.PROGRESS_VOICE]
        assert SocialProfile.objects.get(pk=profile.pk).bootstrapped_at is not None

    def test_a_voice_that_could_not_be_learned_fails_the_job_and_leaves_the_profile_open(
        self, profile, bootstrap
    ):
        bootstrap(VoiceRefresh("failed", reason="model said no: secret detail"))
        with pytest.raises(JobError) as caught:
            tasks.bootstrap_profile(ctx(profile))
        assert caught.value.code == "voice_failed"
        assert "secret detail" not in str(caught.value)
        assert SocialProfile.objects.get(pk=profile.pk).bootstrapped_at is None

    def test_a_job_without_a_profile_is_refused(self, profile, bootstrap):
        bootstrap(VoiceRefresh("created"))
        bad = jobs.JobContext(
            ctx(profile).id, profile.user_id, None, tasks.BOOTSTRAP_KIND, {}
        )
        with pytest.raises(JobError):
            tasks.bootstrap_profile(bad)
