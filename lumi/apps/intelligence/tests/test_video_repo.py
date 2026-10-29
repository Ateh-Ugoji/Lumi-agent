"""``VideoRepo``: the analysis cache over ``video_analysis_records``."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest
from asgiref.sync import async_to_sync

from apps.intelligence.models import VideoAnalysisRecord, VideoAnalysisStatus
from apps.intelligence.repos import PeerPostRepo, VideoRepo
from lumi_ai import ports
from lumi_ai.ports import MediaRef, PeerPostIn, PostMetrics
from lumi_ai.video.codec import PROMPT_VERSION
from lumi_ai.video.fake import sample_analysis

pytestmark = pytest.mark.django_db

URL = "https://video.twimg.com/a.mp4"


def call(fn, *args, **kwargs):
    return async_to_sync(fn)(*args, **kwargs)


@pytest.fixture
def stored_video(profile):
    post = PeerPostIn(
        platform="x",
        external_id="v1",
        author_handle="rival",
        text="a video post",
        published_at=datetime(2026, 10, 1, tzinfo=UTC),
        metrics=PostMetrics(likes=1),
        media=(MediaRef(kind="video", url=URL),),
    )
    call(PeerPostRepo().save_peer_posts, profile.pk, [post])
    return URL


def test_the_repo_satisfies_the_port():
    assert isinstance(VideoRepo(), ports.VideoAnalysisStore)


def test_save_then_cached_round_trips_the_analysis(stored_video):
    repo = VideoRepo()
    analysis = sample_analysis(URL, provider="gemini")
    assert call(repo.save, [analysis], model="gemini-3.5-flash-lite") == 1
    cached = call(repo.cached, [URL], provider="gemini", prompt_version=PROMPT_VERSION)
    assert cached == {URL: analysis}
    row = VideoAnalysisRecord.objects.get()
    assert row.status == VideoAnalysisStatus.OK and row.model == "gemini-3.5-flash-lite"


def test_cache_is_keyed_by_provider_and_prompt_version(stored_video):
    repo = VideoRepo()
    call(repo.save, [sample_analysis(URL, provider="gemini")], model="m")
    assert (
        call(repo.cached, [URL], provider="other", prompt_version=PROMPT_VERSION) == {}
    )
    assert call(repo.cached, [URL], provider="gemini", prompt_version="video-v0") == {}


def test_saving_again_updates_the_same_row(stored_video):
    repo = VideoRepo()
    first = sample_analysis(URL, provider="gemini")
    call(repo.save, [first], model="m")
    call(repo.save, [replace(first, cut_count=99)], model="m2")
    assert VideoAnalysisRecord.objects.count() == 1
    cached = call(repo.cached, [URL], provider="gemini", prompt_version=PROMPT_VERSION)
    assert cached[URL].cut_count == 99


def test_a_url_without_a_media_row_is_not_cached_and_says_so(stored_video):
    repo = VideoRepo()
    other = "https://video.twimg.com/unknown.mp4"
    assert call(repo.save, [sample_analysis(other, provider="gemini")], model="m") == 0
    assert (
        call(
            repo.save_failure,
            other,
            provider="gemini",
            model="m",
            prompt_version=PROMPT_VERSION,
            error="x",
        )
        is False
    )
    assert VideoAnalysisRecord.objects.count() == 0


def test_a_failure_is_recorded_but_is_not_a_cache_hit_and_a_success_replaces_it(
    stored_video,
):
    repo = VideoRepo()
    kwargs = {"provider": "gemini", "model": "m", "prompt_version": PROMPT_VERSION}
    assert call(repo.save_failure, URL, error="HTTP 429", **kwargs) is True
    assert (
        call(repo.cached, [URL], provider="gemini", prompt_version=PROMPT_VERSION) == {}
    )
    assert VideoAnalysisRecord.objects.get().status == VideoAnalysisStatus.FAILED
    call(repo.save, [sample_analysis(URL, provider="gemini")], model="m")
    assert VideoAnalysisRecord.objects.get().status == VideoAnalysisStatus.OK
    call(repo.save_failure, URL, error="late failure", **kwargs)
    row = VideoAnalysisRecord.objects.get()
    assert row.status == VideoAnalysisStatus.OK and row.error == ""


def test_a_stored_row_that_no_longer_parses_is_skipped_not_raised(stored_video):
    repo = VideoRepo()
    call(repo.save, [sample_analysis(URL, provider="gemini")], model="m")
    VideoAnalysisRecord.objects.update(result=["not", "an", "object"])
    assert (
        call(repo.cached, [URL], provider="gemini", prompt_version=PROMPT_VERSION) == {}
    )
