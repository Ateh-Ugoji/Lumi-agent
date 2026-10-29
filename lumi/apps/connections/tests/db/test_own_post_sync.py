# ruff: noqa: F811
"""``OwnPostSync`` over the real database with a mocked Post for Me feed and no network."""

from __future__ import annotations

import copy

import httpx
import pytest
from asgiref.sync import async_to_sync

from apps.connections import own_post_sync
from apps.connections.models import ConnectedAccount, IngestPass
from apps.connections.own_post_sync import DjangoOwnPostSync
from apps.connections.own_posts import OwnPostsResult
from apps.connections.tests.db.test_api import (  # noqa: F401  (fixtures)
    PFM_ENV,
    env,
    providers,
    wiring,
)
from apps.connections.tests.fakes import fixture
from apps.profiles.models import MetricSnapshot, Post, SocialHandle, SocialProfile
from lumi_ai import cancel
from lumi_ai.ports import (
    OwnPostSync,
    PostIn,
    ProviderUnavailable,
    UnsupportedPlatform,
)

pytestmark = pytest.mark.django_db

FEED = "/v1/social-account-feeds/sa_1"


@pytest.fixture
def own(user) -> SocialProfile:
    handle = SocialHandle.objects.create(platform="x", handle_normalized="ateh")
    return SocialProfile.objects.create(user=user, handle=handle)


@pytest.fixture
def linked(own, user, env, providers) -> SocialProfile:
    env(PFM_ENV)
    ConnectedAccount.objects.create(
        user=user,
        social_profile=own,
        provider="pfm",
        external_account_id="sa_1",
        platform="x",
        handle="ateh",
    )
    return own


def serve(providers, *pages: dict):
    """The feed answers these pages in order, one per request."""
    queue = list(pages)
    providers.on(
        "pfm", {("GET", FEED): lambda request: httpx.Response(200, json=queue.pop(0))}
    )


def both_pages() -> list[dict]:
    return [fixture("pfm_feed_x_page1.json"), fixture("pfm_feed_x_page2.json")]


def without(page: dict, *ids: str) -> dict:
    page = copy.deepcopy(page)
    page["data"] = [i for i in page["data"] if i["platform_post_id"] not in ids]
    return page


def sync(profile_id: int, platform=None):
    return async_to_sync(DjangoOwnPostSync().sync_own_posts)(profile_id, platform)


def test_it_satisfies_the_port() -> None:
    assert isinstance(DjangoOwnPostSync(), OwnPostSync)


def test_the_feed_is_stored_and_the_pass_is_recorded(linked, providers) -> None:
    serve(providers, *both_pages())
    out = sync(linked.pk)
    assert out["stored"] == 5 and out["platform"] == "x" and out["handle"] == "ateh"
    assert out["pages"] == 2 and out["complete"] is True
    assert Post.objects.filter(author_id=linked.handle_id).count() == 5
    run = IngestPass.objects.get()
    assert (run.source, run.complete, run.handle_id) == ("pfm", True, linked.handle_id)


def test_a_post_without_metrics_gets_no_snapshot(linked, providers) -> None:
    serve(providers, *both_pages())
    sync(linked.pk)
    bare = Post.objects.get(platform_post_id="99")
    assert not MetricSnapshot.objects.filter(post=bare).exists()
    assert MetricSnapshot.objects.filter(post__platform_post_id="101").exists()


def test_repeating_the_sync_adds_no_posts(linked, providers) -> None:
    serve(providers, *both_pages(), *both_pages())
    sync(linked.pk)
    sync(linked.pk)
    assert Post.objects.count() == 5 and IngestPass.objects.count() == 2


def test_a_post_missing_from_two_complete_passes_is_flagged(linked, providers) -> None:
    page1, page2 = both_pages()
    serve(providers, page1, page2, *[without(page1, "99"), page2] * 2)
    sync(linked.pk)
    assert sync(linked.pk)["flagged_deleted"] == 0
    third = sync(linked.pk)
    assert third["flagged_deleted"] == 1
    assert Post.objects.get(platform_post_id="99").is_deleted_suspect is True


def test_a_post_that_comes_back_is_restored(linked, providers) -> None:
    page1, page2 = both_pages()
    gone = [without(page1, "99"), page2]
    serve(providers, page1, page2, *gone, *gone, page1, page2)
    for _ in range(3):
        sync(linked.pk)
    assert Post.objects.get(platform_post_id="99").is_deleted_suspect is True
    sync(linked.pk)  # ``upsert_posts`` clears the mark of every post the feed returns
    assert Post.objects.get(platform_post_id="99").is_deleted_suspect is False


def test_an_empty_read_is_stored_but_never_counts_as_a_pass(linked, providers) -> None:
    empty = copy.deepcopy(fixture("pfm_feed_x_page2.json"))
    empty["data"] = []
    serve(providers, empty)
    out = sync(linked.pk)
    assert out["stored"] == 0 and out["complete"] is False
    assert IngestPass.objects.get().complete is False


def test_a_read_cut_short_by_the_page_limit_is_not_a_complete_pass(
    linked, providers, monkeypatch
) -> None:
    monkeypatch.setattr(own_post_sync, "OWN_POST_MAX_PAGES", 1)
    page1 = fixture("pfm_feed_x_page1.json")  # all within 30 days and has_more
    serve(providers, page1)
    out = sync(linked.pk)
    assert out["pages"] == 1 and out["complete"] is False


def test_threads_are_renumbered_after_the_save(linked, monkeypatch) -> None:
    from datetime import UTC, datetime

    def post(external_id, hour):
        return PostIn(
            platform="x",
            external_id=external_id,
            text=f"t{external_id}",
            published_at=datetime(2026, 10, 20, hour, tzinfo=UTC),
            conversation_id="c1",
            source="pfm",
        )

    async def fake(*args, **kwargs):
        return OwnPostsResult((post("2", 11), post("1", 10)), 0, 1, "end")

    monkeypatch.setattr(own_post_sync, "collect_own_posts", fake)
    sync(linked.pk)
    first = Post.objects.get(platform_post_id="1")
    assert (first.thread_position, first.is_thread_head) == (1, True)
    assert Post.objects.get(platform_post_id="2").thread_position == 2


def test_nothing_is_asked_of_pfm_when_no_account_is_connected(
    own, env, providers
) -> None:
    env(PFM_ENV)
    providers.on("pfm", {})  # any request fails the test
    with pytest.raises(ProviderUnavailable, match="connect one first"):
        sync(own.pk)
    assert providers.requests("pfm") == []


def test_a_revoked_account_is_not_read(linked, providers) -> None:
    ConnectedAccount.objects.update(status="revoked")
    with pytest.raises(ProviderUnavailable):
        sync(linked.pk)
    assert providers.requests("pfm") == []


def test_another_platform_than_the_profiles_is_refused(linked, providers) -> None:
    with pytest.raises(UnsupportedPlatform):
        sync(linked.pk, "linkedin")
    assert providers.requests("pfm") == []


def test_an_unknown_profile_is_refused(linked) -> None:
    with pytest.raises(ProviderUnavailable, match="profile not found"):
        sync(10**9)


def test_it_says_so_when_pfm_has_no_key(own, user, env, providers) -> None:
    ConnectedAccount.objects.create(
        user=user, social_profile=own, provider="pfm", external_account_id="sa_1"
    )
    with pytest.raises(ProviderUnavailable, match="not configured"):
        sync(own.pk)


def test_a_sync_whose_tool_call_timed_out_commits_nothing(linked, providers) -> None:
    serve(providers, *both_pages())
    token = cancel.CancelToken()
    token.cancel_nowait()
    reset = cancel.current.set(token)
    try:
        with pytest.raises(cancel.WriteCancelled):
            sync(linked.pk)
    finally:
        cancel.current.reset(reset)
    assert Post.objects.count() == 0 and IngestPass.objects.count() == 0


def test_a_timeout_between_the_save_and_the_pass_records_no_pass(
    linked, providers, monkeypatch
) -> None:
    serve(providers, *both_pages())
    token = cancel.CancelToken()
    real = own_post_sync.finalize_pass

    async def time_out_then_close(*args, **kwargs):
        token.cancel_nowait()  # the save above already committed
        return await real(*args, **kwargs)

    monkeypatch.setattr(own_post_sync, "finalize_pass", time_out_then_close)
    reset = cancel.current.set(token)
    try:
        with pytest.raises(cancel.WriteCancelled):
            sync(linked.pk)
    finally:
        cancel.current.reset(reset)
    assert Post.objects.count() == 5 and IngestPass.objects.count() == 0


def test_an_account_of_another_profile_is_not_used(
    own, other_user, env, providers
) -> None:
    env(PFM_ENV)
    elsewhere = SocialProfile.objects.create(
        user=other_user,
        handle=SocialHandle.objects.create(platform="x", handle_normalized="other"),
    )
    ConnectedAccount.objects.create(
        user=other_user,
        social_profile=elsewhere,
        provider="pfm",
        external_account_id="sa_1",
    )
    with pytest.raises(ProviderUnavailable, match="connect one first"):
        sync(own.pk)
    assert providers.requests("pfm") == []
