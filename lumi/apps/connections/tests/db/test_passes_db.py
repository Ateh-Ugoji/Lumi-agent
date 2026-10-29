"""The pass store against Postgres: the two-miss flow on real ``posts``."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from asgiref.sync import async_to_sync
from django.db import IntegrityError, transaction

from apps.connections.models import IngestPass
from apps.connections.passes import finalize_pass
from apps.connections.stores import DjangoPassStore
from apps.profiles import services
from apps.profiles.models import Post
from lumi_ai.ports import PostIn

T0 = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)
H = timedelta(hours=1)


def run(handle_id, at, fetched, *, complete=True):
    published = T0 - timedelta(days=2)
    return async_to_sync(finalize_pass)(
        DjangoPassStore(),
        handle_id,
        fetched_ids=fetched,
        source="xpoz",
        pass_started=at,
        pass_complete=complete,
        fetched_window=(published - timedelta(days=1), at),
    )


def seed(external, handle_id, days=2):
    services.upsert_posts(
        handle_id,
        [
            PostIn(
                external_id=external,
                platform="x",
                text="hi",
                published_at=T0 - timedelta(days=days),
            )
        ],
    )


@pytest.fixture
def handle_id(db):
    return services.get_or_create_handle("x", "owner", origin="profile")


def test_two_complete_misses_flag_a_stored_post(handle_id) -> None:
    seed("p1", handle_id)
    seed("other", handle_id)
    assert run(handle_id, T0 - H, {"p1", "other"}).flagged_deleted == 0
    assert run(handle_id, T0 + H, {"other"}).flagged_deleted == 0
    assert run(handle_id, T0 + 3 * H, {"other"}).flagged_deleted == 1

    flagged = dict(Post.objects.values_list("platform_post_id", "is_deleted_suspect"))
    assert flagged == {"p1": True, "other": False}
    assert Post.objects.get(platform_post_id="other").last_seen_at == T0 + 3 * H
    assert IngestPass.objects.filter(handle_id=handle_id, complete=True).count() == 3


def test_a_returning_post_is_cleared_and_other_authors_are_untouched(handle_id) -> None:
    stranger = services.get_or_create_handle("x", "stranger")
    seed("p1", handle_id)
    seed("p1", stranger)
    run(handle_id, T0 - H, {"p1"})
    run(handle_id, T0 + H, set())
    run(handle_id, T0 + 3 * H, set())
    assert Post.objects.get(author_id=handle_id).is_deleted_suspect is True
    assert Post.objects.get(author_id=stranger).is_deleted_suspect is False
    assert run(handle_id, T0 + 5 * H, {"p1"}).cleared == 1
    assert Post.objects.get(author_id=handle_id).is_deleted_suspect is False


def test_a_pass_is_recorded_once_per_start_time(handle_id) -> None:
    run(handle_id, T0, set())
    run(handle_id, T0, set(), complete=False)  # a retry of the same pass updates it
    row = IngestPass.objects.get(handle_id=handle_id)
    assert row.complete is False and row.source == "xpoz"
    with pytest.raises(IntegrityError), transaction.atomic():
        IngestPass.objects.create(
            handle_id=handle_id, started_at=T0, source="xpoz", complete=True
        )


def test_an_unknown_source_is_refused_by_the_table(handle_id) -> None:
    with pytest.raises(IntegrityError), transaction.atomic():
        IngestPass.objects.create(
            handle_id=handle_id, started_at=T0, source="nope", complete=True
        )


def test_an_interrupted_pass_does_not_become_the_first_miss(handle_id) -> None:
    seed("p1", handle_id)
    run(handle_id, T0 - H, {"p1"})
    run(handle_id, T0 + H, set(), complete=False)
    assert run(handle_id, T0 + 3 * H, set()).flagged_deleted == 0
    assert run(handle_id, T0 + 5 * H, set()).flagged_deleted == 1


def test_the_previous_pass_is_strictly_before_this_one(handle_id) -> None:
    store = DjangoPassStore()
    run(handle_id, T0 - H, set())
    run(handle_id, T0, set())
    assert async_to_sync(store.last_complete_pass)(handle_id, T0) == T0 - H
    assert async_to_sync(store.last_complete_pass)(handle_id, T0 - H) is None


def test_the_store_only_reads_and_writes_the_posts_of_its_author(handle_id) -> None:
    stranger = services.get_or_create_handle("x", "stranger")
    seed("mine", handle_id)
    seed("theirs", stranger)
    store = DjangoPassStore()
    assert [p.external_id for p in async_to_sync(store.posts)(handle_id)] == ["mine"]
    theirs = Post.objects.get(author_id=stranger)
    async_to_sync(store.save_pass)(
        handle_id,
        started_at=T0,
        source="xpoz",
        complete=True,
        seen=[theirs.pk],
        flag=[theirs.pk],
        clear=[],
    )
    theirs.refresh_from_db()
    assert theirs.is_deleted_suspect is False and theirs.last_seen_at != T0
