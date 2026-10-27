"""Parity tests: places where the new backend knowingly differs from the legacy one.

Each test is named in the parity matrix of ``plan/estado/ARCHITECT.md``.
"""

from datetime import UTC, datetime

import pytest
from django.db.models import Sum

from apps.profiles import services
from apps.profiles.models import MetricSnapshot, Post, PostMedia
from lumi_ai.ports import MediaRef, PostIn, PostMetrics

URL = "/api/v1/profiles/{}/analytics"


def post(external_id, **metrics):
    return PostIn(
        platform="x",
        external_id=external_id,
        text="word " * 5,
        kind="original",
        published_at=datetime(2026, 10, 1, tzinfo=UTC),
        metrics=PostMetrics(**metrics),
    )


def test_row_18_analytics_adds_the_latest_reading_of_each_post_not_every_reading(
    api, profile
):
    """The legacy code summed every snapshot, so a post read three times counted three times."""
    services.upsert_posts(
        profile.handle_id, [post("1", views=100, likes=10), post("2", views=50)]
    )
    services.upsert_posts(profile.handle_id, [post("1", views=150, likes=12)])
    services.upsert_posts(profile.handle_id, [post("1", views=200, likes=20)])

    legacy_total = MetricSnapshot.objects.aggregate(v=Sum("views"))["v"]
    body = api.get(URL.format(profile.pk)).json()

    assert legacy_total == 500  # 100 + 150 + 200 + 50: what the old code reported
    assert body["total_impressions"] == 250  # 200 + 50
    assert body["total_likes"] == 20
    assert body["is_live_data"] is True


def test_row_21_media_of_unknown_type_is_stored_as_null_not_guessed(profile):
    """Ports 1.9. The schema first required a type; a source with a bare URL has none to give."""
    services.upsert_posts(
        profile.handle_id,
        [
            PostIn(
                platform="x",
                external_id="m",
                text="word " * 5,
                kind="original",
                published_at=datetime(2026, 10, 1, tzinfo=UTC),
                media=(MediaRef(None, "https://x/bare.jpg"),),
            )
        ],
    )
    assert list(PostMedia.objects.values_list("kind", "url")) == [
        (None, "https://x/bare.jpg")
    ]


@pytest.mark.django_db
def test_row_24_the_truncation_flag_follows_the_latest_fetch_not_a_sticky_one(
    handle_id,
):
    """Legacy kept ``text_truncated`` once set. Here it describes the caption that is stored."""
    cut = "x" * 274 + "…"
    services.upsert_posts(handle_id, [_typed("300", text=cut, text_truncated=True)])
    assert Post.objects.get(platform_post_id="300").text_truncated is True
    services.upsert_posts(
        handle_id, [_typed("300", text="the whole text", text_truncated=False)]
    )
    row = Post.objects.get(platform_post_id="300")
    assert (row.text_truncated, row.caption) == (False, "the whole text")
    services.upsert_posts(handle_id, [_typed("300", text=cut, text_truncated=True)])
    assert Post.objects.get(platform_post_id="300").text_truncated is True


@pytest.mark.django_db
def test_row_25_a_snapshot_is_appended_only_when_a_metric_changed(handle_id):
    """Legacy also appended every 6 hours and at the 24h, 72h, 7d and 30d marks."""
    first = _typed("301", metrics=PostMetrics(likes=10, views=100))
    services.upsert_posts(handle_id, [first])
    for _ in range(3):  # repeated fetches with the same numbers
        services.upsert_posts(handle_id, [first])
    assert MetricSnapshot.objects.filter(post__platform_post_id="301").count() == 1
    stamp = Post.objects.get(platform_post_id="301").last_checked_at
    assert (
        stamp is not None
    )  # the condition on row 25: an unchanged check is still recorded
    services.upsert_posts(handle_id, [first])
    assert Post.objects.get(platform_post_id="301").last_checked_at > stamp
    services.upsert_posts(
        handle_id, [_typed("301", metrics=PostMetrics(likes=11, views=100))]
    )
    assert MetricSnapshot.objects.filter(post__platform_post_id="301").count() == 2


@pytest.fixture
def handle_id():
    return services.get_or_create_handle("x", "@Ateh", origin="profile")


def _typed(external_id, **kw):
    base = {
        "platform": "x",
        "external_id": external_id,
        "text": "word " * 5,
        "kind": "original",
        "published_at": datetime(2026, 10, 1, tzinfo=UTC),
    }
    return PostIn(**{**base, **kw})


@pytest.mark.django_db
def test_row_27_the_match_author_picture_is_the_handle_picture_not_a_copy(api, profile):
    """Legacy copied the picture into each ``listening_matches`` row, so a match found before
    the picture was known kept NULL for good. Here the match reads the handle's picture."""
    hid = services.get_or_create_handle("x", "sama", origin="niche")
    [post_id] = services.upsert_posts(hid, [post("901", likes=1)]).post_ids
    services.record_listening_match(profile.pk, post_id)
    url = f"/api/v1/trends/matches?profile_id={profile.pk}"
    assert api.get(url).json()["matches"][0]["author_avatar_url"] is None
    services.get_or_create_handle(
        "x", "sama", origin="niche", avatar_url="https://img.example/sama.png"
    )
    assert (
        api.get(url).json()["matches"][0]["author_avatar_url"]
        == "https://img.example/sama.png"
    )
