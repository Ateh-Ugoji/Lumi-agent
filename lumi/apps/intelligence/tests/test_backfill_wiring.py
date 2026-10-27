"""``backfill_posts`` and the sync jobs over CONNECT's ``DjangoOwnPostSync``.

The tool and the jobs are wired for real (``get_wiring``); only the feed read (an external call)
and the style/indexer stand-ins are replaced.
"""

from __future__ import annotations

import json
import time
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from asgiref.sync import async_to_sync

from apps.connections import own_post_sync
from apps.connections.models import ConnectedAccount
from apps.connections.own_post_sync import DjangoOwnPostSync
from apps.connections.own_posts import OwnPostsResult
from apps.core import jobs
from apps.core.jobs import JobError
from apps.core.models import BackgroundJob
from apps.intelligence import tasks, wiring
from apps.intelligence.repos import PostRepo
from apps.profiles.models import Post
from lumi_ai import ports
from lumi_ai.config import ENV_FIELDS, AIConfig
from lumi_ai.style.service import VoiceRefresh
from lumi_ai.tests.agent.harness import call, make_rig, say, use
from lumi_ai.tools.registry import ToolContext


@pytest.fixture
def real_wiring(monkeypatch, tmp_path):
    for name in ENV_FIELDS:
        if name.endswith("api_key"):
            monkeypatch.delenv(name.upper(), raising=False)
    monkeypatch.setenv("CHROMA_PATH", str(tmp_path / "chroma"))
    wiring.get_wiring.cache_clear()
    yield wiring.get_wiring()
    wiring.get_wiring.cache_clear()


class SpySync:
    """Stands where ``DjangoOwnPostSync`` is: records the call, answers like the real one."""

    def __init__(self, answer=None, error=None):
        self.calls = []
        self.answer = answer or {
            "platform": "x",
            "handle": "ateh",
            "stored": 3,
            "skipped": 0,
            "pages": 1,
            "complete": True,
            "flagged_deleted": 0,
        }
        self.error = error

    async def sync_own_posts(self, profile_id, platform=None):
        self.calls.append((profile_id, platform))
        if self.error:
            raise self.error
        return self.answer


class TestTool:
    def test_it_is_registered_with_the_django_implementation(self, real_wiring):
        assert "backfill_posts" in real_wiring.registry.names
        assert isinstance(real_wiring.post_sync, DjangoOwnPostSync)

    def test_it_is_a_write_so_the_loop_hands_it_a_cancel_token(self, real_wiring):
        assert real_wiring.registry.get("backfill_posts").writes is True

    def test_it_syncs_the_profile_of_the_turn_and_returns_the_sync_result(
        self, real_wiring, monkeypatch
    ):
        spy = SpySync()
        monkeypatch.setattr(DjangoOwnPostSync, "sync_own_posts", spy.sync_own_posts)
        out = async_to_sync(real_wiring.registry.call)(
            ToolContext(profile_id=42),
            "backfill_posts",
            {"profile_id": 999, "platform": "x", "reason": "the user asked to refresh"},
        )
        assert out == spy.answer
        assert spy.calls == [(42, "x")], "the turn decides the profile, not the model"

    def test_a_provider_problem_comes_back_as_an_error_not_an_exception(
        self, real_wiring, monkeypatch
    ):
        spy = SpySync(
            error=ports.ProviderUnavailable(
                "no connected x account", provider="connections"
            )
        )
        monkeypatch.setattr(DjangoOwnPostSync, "sync_own_posts", spy.sync_own_posts)
        out = async_to_sync(real_wiring.registry.call)(
            ToolContext(profile_id=1),
            "backfill_posts",
            {"profile_id": 1, "reason": "refresh"},
        )
        assert (
            out["provider"] == "connections"
            and "no connected x account" in out["error"]
        )


class TestToolTimeout:
    """The real loop, the real tool, the real sync over the database; only the feed is faked."""

    pytestmark = pytest.mark.django_db(transaction=True)

    @pytest.fixture
    def feed(self, profile, monkeypatch):
        ConnectedAccount.objects.create(
            user=profile.user,
            social_profile=profile,
            provider="pfm",
            external_account_id="sa_1",
            platform="x",
            handle="ateh",
        )
        monkeypatch.setattr(own_post_sync.accounts, "get_config", lambda: None)
        monkeypatch.setattr(own_post_sync.accounts, "missing_env", lambda *_: [])
        monkeypatch.setattr(own_post_sync.accounts, "make_pfm", lambda: None)

        async def collect(*_a, **_k):
            post = ports.PostIn("x", "p1", "a post", datetime(2026, 9, 1, tzinfo=UTC))
            return OwnPostsResult((post,), 0, 1, "end")

        monkeypatch.setattr(own_post_sync, "collect_own_posts", collect)

    def _run(self, profile, real_wiring, timeout):
        spec = real_wiring.registry.get("backfill_posts")
        rig = make_rig(
            [use(call("backfill_posts", {})), say("Done.")],
            [spec],
            config=AIConfig(tool_timeout_seconds=timeout),
        )
        rig.loop.deps.profiles.profile = ports.ProfileInfo(
            profile.id, "Ana", "ateh", "x", ("x",)
        )
        async_to_sync(rig.run)("refresh my posts", profile.id)
        return rig

    def test_a_fast_sync_commits(self, profile, real_wiring, feed):
        rig = self._run(profile, real_wiring, timeout=10)
        assert Post.objects.filter(author_id=profile.handle_id).count() == 1
        assert json.loads(rig.llm.tool_messages(1)[0]["content"])["stored"] == 1

    def test_a_sync_that_timed_out_leaves_no_post(
        self, profile, real_wiring, feed, monkeypatch
    ):
        real = own_post_sync.services.upsert_posts

        def slow(*args, **kwargs):
            done = real(*args, **kwargs)
            time.sleep(0.5)  # inserted, not yet committed: the loop gives up here
            return done

        monkeypatch.setattr(own_post_sync.services, "upsert_posts", slow)
        rig = self._run(profile, real_wiring, timeout=0.15)
        time.sleep(0.8)
        assert Post.objects.filter(author_id=profile.handle_id).count() == 0
        assert (
            "timed out" in json.loads(rig.llm.tool_messages(1)[0]["content"])["error"]
        )


class Style:
    def __init__(self, outcome):
        self.outcome, self.calls = outcome, []

    async def ensure_voice(self, profile_id):
        self.calls.append(profile_id)
        return self.outcome


class Indexer:
    def __init__(self):
        self.seen = []

    def index_posts(self, posts):
        self.seen.extend(posts)
        return len(posts)


def ctx(profile, kind):
    return jobs.JobContext(uuid.uuid4(), profile.user_id, profile.pk, kind, {})


@pytest.fixture
def jobs_rig(monkeypatch):
    progress = []
    monkeypatch.setattr(jobs, "set_progress", lambda _id, pct: progress.append(pct))

    def arrange(sync, outcome=None):
        outcome = outcome or VoiceRefresh("created", posts_found=1)
        style, indexer = Style(outcome), Indexer()
        monkeypatch.setattr(
            wiring,
            "get_wiring",
            lambda: SimpleNamespace(
                posts=PostRepo(),
                config=AIConfig(),
                style=style,
                indexer=indexer,
                post_sync=sync,
            ),
        )
        return style, indexer, progress

    return arrange


class TestJobs:
    def test_refresh_is_registered_for_the_kind_the_profiles_app_enqueues(self):
        from apps.profiles.views import REFRESH_KIND

        assert tasks.REFRESH_KIND == REFRESH_KIND
        assert jobs._HANDLERS[REFRESH_KIND] is tasks.refresh_profile

    def test_bootstrap_syncs_the_account_before_it_indexes(self, profile, jobs_rig):
        sync = SpySync()
        _, _, progress = jobs_rig(sync)
        out = tasks.bootstrap_profile(ctx(profile, tasks.BOOTSTRAP_KIND))
        assert sync.calls == [(profile.pk, None)]
        assert out["sync"] == "ok" and out["posts_synced"] == 3
        assert progress == [
            tasks.PROGRESS_SYNCED,
            tasks.PROGRESS_INDEXED,
            tasks.PROGRESS_VOICE,
        ]

    def test_bootstrap_without_a_connected_account_still_finishes(
        self, profile, jobs_rig
    ):
        sync = SpySync(
            error=ports.ProviderUnavailable(
                "no connected x account", provider="connections"
            )
        )
        style, _, _ = jobs_rig(sync, VoiceRefresh("needs_style_questions"))
        out = tasks.bootstrap_profile(ctx(profile, tasks.BOOTSTRAP_KIND))
        assert out["sync"] == "unavailable" and out["posts_synced"] == 0
        assert out["voice"] == "needs_style_questions" and style.calls == [profile.pk]

    def test_refresh_syncs_then_indexes_what_is_stored(self, profile, jobs_rig):
        sync = SpySync()
        _, indexer, progress = jobs_rig(sync)
        from apps.profiles import services

        services.upsert_posts(
            profile.handle_id,
            [ports.PostIn("x", "p1", "first", datetime(2026, 9, 1, tzinfo=UTC))],
        )
        out = tasks.refresh_profile(ctx(profile, tasks.REFRESH_KIND))
        assert sync.calls == [(profile.pk, None)]
        assert out == {
            "posts_synced": 3,
            "posts_indexed": 1,
            "complete": True,
            "flagged_deleted": 0,
        }
        assert len(indexer.seen) == 1 and progress == [tasks.PROGRESS_SYNCED]

    def test_refresh_fails_the_job_when_the_feed_cannot_be_read(
        self, profile, jobs_rig
    ):
        sync = SpySync(
            error=ports.ProviderUnavailable("pfm said: secret", provider="pfm")
        )
        _, indexer, _ = jobs_rig(sync)
        with pytest.raises(JobError) as caught:
            tasks.refresh_profile(ctx(profile, tasks.REFRESH_KIND))
        assert caught.value.code == "sync_failed" and "secret" not in str(caught.value)
        assert indexer.seen == []

    def test_refresh_without_a_profile_is_refused(self, profile, jobs_rig):
        jobs_rig(SpySync())
        bad = jobs.JobContext(
            uuid.uuid4(), profile.user_id, None, tasks.REFRESH_KIND, {}
        )
        with pytest.raises(JobError):
            tasks.refresh_profile(bad)

    def test_the_job_enqueued_by_the_endpoint_runs_end_to_end(
        self, profile, jobs_rig, settings, django_capture_on_commit_callbacks
    ):
        settings.LUMI_JOB_DISPATCH = "eager"
        sync = SpySync()
        jobs_rig(sync)
        with django_capture_on_commit_callbacks(execute=True):
            job_id, _ = jobs.enqueue(
                profile.user_id, tasks.REFRESH_KIND, profile_id=profile.pk
            )
        job = BackgroundJob.objects.get(pk=job_id)
        assert job.status == "succeeded" and sync.calls == [(profile.pk, None)]
