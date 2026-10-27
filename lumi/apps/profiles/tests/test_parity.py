"""Parity tests: places where the new backend knowingly differs from the legacy one.

Each test is named in the parity matrix of ``plan/estado/ARCHITECT.md``.
"""

from datetime import UTC, datetime

from django.db.models import Sum

from apps.profiles import services
from apps.profiles.models import MetricSnapshot, PostMedia
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
