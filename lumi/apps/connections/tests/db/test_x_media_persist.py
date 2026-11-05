"""X media from Xpoz is stored with an unknown kind, not guessed and not dropped."""

from __future__ import annotations

import pytest

from apps.connections.ingest import map_xpoz_post
from apps.profiles import services
from apps.profiles.models import PostMedia

pytestmark = pytest.mark.django_db


def test_x_media_urls_are_stored_with_a_null_kind() -> None:
    handle_id = services.get_or_create_handle("x", "@Ateh", origin="profile")
    post = map_xpoz_post(
        {
            "id": 7,
            "text": "hi",
            "createdAt": "2026-10-20T10:00:00Z",
            "authorUsername": "Ateh",
            "mediaUrls": ["https://pbs.example/a.jpg", "https://video.example/b.mp4"],
        }
    )
    services.upsert_posts(handle_id, [post])
    stored = list(PostMedia.objects.order_by("position").values_list("kind", "url"))
    assert stored == [
        (None, "https://pbs.example/a.jpg"),
        (None, "https://video.example/b.mp4"),
    ]
