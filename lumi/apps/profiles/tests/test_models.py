"""Constraint tests: the database, not the service layer, enforces the schema rules."""

import pytest
from django.db import DataError, IntegrityError, connection, transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.profiles.models import (
    Alert,
    ListeningKeyword,
    ListeningMatch,
    MetricSnapshot,
    PollConfig,
    Post,
    PostMedia,
    ProfileBaseline,
    SocialHandle,
    SocialProfile,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def user():
    return User.objects.create_user("owner@example.com")


@pytest.fixture
def handle():
    return SocialHandle.objects.create(platform="x", handle_normalized="somebody")


@pytest.fixture
def profile(user, handle):
    return SocialProfile.objects.create(user=user, handle=handle)


@pytest.fixture
def post(handle):
    return Post.objects.create(author=handle, platform_post_id="100")


def fails(fn):
    with pytest.raises(IntegrityError), transaction.atomic():
        fn()


def test_handle_unique_per_platform_and_other_platform_ok(handle):
    fails(
        lambda: SocialHandle.objects.create(platform="x", handle_normalized="somebody")
    )
    SocialHandle.objects.create(platform="linkedin", handle_normalized="somebody")


@pytest.mark.parametrize("bad", ["Upper", "@at", "has space", ""])
def test_handle_must_be_normalized(bad):
    fails(lambda: SocialHandle.objects.create(platform="x", handle_normalized=bad))


def test_handle_longer_than_100_is_rejected():
    with pytest.raises(DataError), transaction.atomic():
        SocialHandle.objects.create(platform="x", handle_normalized="a" * 101)


def test_handle_platform_and_origin_are_checked():
    fails(
        lambda: SocialHandle.objects.create(platform="youtube", handle_normalized="a")
    )
    fails(
        lambda: SocialHandle.objects.create(
            platform="x", handle_normalized="a", origin="nope"
        )
    )


def test_two_users_can_follow_the_same_handle_but_not_twice(user, handle):
    other = User.objects.create_user("other@example.com")
    SocialProfile.objects.create(user=user, handle=handle)
    SocialProfile.objects.create(user=other, handle=handle)
    fails(lambda: SocialProfile.objects.create(user=user, handle=handle))


def test_profile_timezone_source_requires_timezone(user, handle):
    fails(
        lambda: SocialProfile.objects.create(
            user=user, handle=handle, timezone_source="inferred"
        )
    )
    fails(
        lambda: SocialProfile.objects.create(user=user, handle=handle, timezone="UTC")
    )
    SocialProfile.objects.create(
        user=user, handle=handle, timezone="UTC", timezone_source="inferred"
    )


def test_handle_with_profile_cannot_be_deleted(profile, handle):
    from django.db.models import ProtectedError

    with pytest.raises(ProtectedError):
        handle.delete()


def test_deleting_user_cascades_to_profile_data(profile, post):
    Alert.objects.create(profile=profile, post=post, kind="spike")
    profile.user.delete()
    assert not SocialProfile.objects.exists() and not Alert.objects.exists()
    assert Post.objects.filter(pk=post.pk).exists()  # shared data survives


def test_post_unique_per_author_and_ck_values(handle, post):
    fails(lambda: Post.objects.create(author=handle, platform_post_id="100"))
    fails(
        lambda: Post.objects.create(author=handle, platform_post_id="101", kind="bogus")
    )
    fails(
        lambda: Post.objects.create(
            author=handle, platform_post_id="102", thread_position=0
        )
    )
    Post.objects.create(
        author=handle, platform_post_id="103", thread_position=1, is_thread_head=None
    )


def test_post_defaults_come_from_the_database(handle):
    with connection.cursor() as c:
        c.execute(
            "INSERT INTO posts (author_id, platform_post_id) VALUES (%s, 'raw') RETURNING id",
            [handle.pk],
        )
        pk = c.fetchone()[0]
    row = Post.objects.get(pk=pk)
    assert row.kind == "original" and row.caption == "" and row.is_stub is False
    assert row.published_at is None and row.is_thread_head is None
    assert row.created_at is not None


def test_metrics_null_is_valid_negative_is_not(post):
    MetricSnapshot.objects.create(post=post, likes=None, views=0)
    fails(
        lambda: MetricSnapshot.objects.create(
            post=post, likes=-1, captured_at=timezone.now()
        )
    )


def test_metric_snapshot_unique_per_instant(post):
    at = timezone.now()
    MetricSnapshot.objects.create(post=post, captured_at=at, likes=1)
    fails(lambda: MetricSnapshot.objects.create(post=post, captured_at=at, likes=2))


def test_alert_only_one_active_per_episode_but_dismissed_can_repeat(profile, post):
    a = Alert.objects.create(
        profile=profile, post=post, kind="spike", trigger="velocity"
    )
    fails(lambda: Alert.objects.create(profile=profile, post=post, kind="spike"))
    Alert.objects.create(
        profile=profile, post=post, kind="niche_match"
    )  # other kind is independent
    Alert.objects.filter(pk=a.pk).update(
        status="dismissed", dismissed_at=timezone.now()
    )
    Alert.objects.create(
        profile=profile, post=post, kind="spike"
    )  # may alert again after dismissal


def test_alert_dismissed_at_requires_dismissed_status(profile, post):
    fails(
        lambda: Alert.objects.create(
            profile=profile, post=post, kind="spike", dismissed_at=timezone.now()
        )
    )
    fails(lambda: Alert.objects.create(profile=profile, post=post, kind="bogus"))
    fails(
        lambda: Alert.objects.create(
            profile=profile, post=post, kind="spike", trigger="bogus"
        )
    )


def test_create_alert_once_pattern_is_atomic_sql(profile, post):
    sql = (
        "INSERT INTO alerts (profile_id, post_id, kind) VALUES (%s, %s, 'spike') "
        "ON CONFLICT (profile_id, post_id, kind) WHERE status = 'active' DO NOTHING RETURNING id"
    )
    with connection.cursor() as c:
        c.execute(sql, [profile.pk, post.pk])
        assert c.fetchone() is not None
        c.execute(sql, [profile.pk, post.pk])
        assert c.fetchone() is None


def test_listening_keyword_unique_ignoring_case_and_not_blank(profile):
    ListeningKeyword.objects.create(profile=profile, keyword="Django")
    fails(lambda: ListeningKeyword.objects.create(profile=profile, keyword="django"))
    fails(lambda: ListeningKeyword.objects.create(profile=profile, keyword=" padded "))
    fails(lambda: ListeningKeyword.objects.create(profile=profile, keyword=""))


def test_poll_config_is_one_per_profile_and_interval_bounded(profile):
    PollConfig.objects.create(profile=profile)
    fails(lambda: PollConfig.objects.create(profile=profile))


@pytest.mark.parametrize("minutes", [0, 1441])
def test_poll_interval_range(profile, minutes):
    fails(lambda: PollConfig.objects.create(profile=profile, interval_minutes=minutes))


def test_poller_claim_is_one_atomic_update(profile):
    PollConfig.objects.create(profile=profile, is_active=True)
    sql = (
        "UPDATE poll_configs SET last_polled_at = now() WHERE is_active AND "
        "(last_polled_at IS NULL OR last_polled_at <= now() - interval_minutes * interval '1 minute') "
        "RETURNING profile_id"
    )
    with connection.cursor() as c:
        c.execute(sql)
        assert c.fetchall() == [(profile.pk,)]
        c.execute(sql)
        assert c.fetchall() == []


def test_baseline_and_media_and_match_rules(profile, post):
    ProfileBaseline.objects.create(profile=profile)
    fails(lambda: ProfileBaseline.objects.create(profile=profile, window_days=0))
    fails(lambda: ProfileBaseline.objects.create(profile=profile, median_views=-1))
    PostMedia.objects.create(
        post=post, kind="video", url="https://x/y.mp4", duration_seconds="3.50"
    )
    fails(
        lambda: PostMedia.objects.create(post=post, kind="video", url="u")
    )  # position 0 again
    fails(
        lambda: PostMedia.objects.create(post=post, position=1, kind="audio", url="u")
    )
    PostMedia.objects.create(post=post, position=2, kind=None, url="u")  # unknown type
    ListeningMatch.objects.create(profile=profile, post=post)
    fails(lambda: ListeningMatch.objects.create(profile=profile, post=post))
