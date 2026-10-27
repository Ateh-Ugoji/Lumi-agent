"""``GET /handles/saved`` is the caller's own list (CONTRATOS §11).

``social_handles`` is a cache of public identities shared by every user. Who picked a handle is
kept in ``user_saved_handles``, so one user's picks never show up in another user's list.
"""

from __future__ import annotations

import pytest
from django.db import connection
from rest_framework.test import APIClient

from apps.connections.models import UserSavedHandle
from apps.profiles import services
from apps.profiles.models import HandleOrigin, SocialHandle

from .test_api import client_for

pytestmark = pytest.mark.django_db

SELECT = "/api/v1/handles/select"
SAVED = "/api/v1/handles/saved"


@pytest.fixture(autouse=True)
def urls(settings):
    settings.ROOT_URLCONF = "apps.connections.tests.db.urls"


def pick(client, handle: str, platform: str = "x") -> None:
    response = client.post(
        SELECT, {"handle": handle, "platform": platform}, format="json"
    )
    assert response.status_code == 200


def names(client, platforms: str = "x") -> list[str]:
    return [
        r["handle"]
        for r in client.get(SAVED, {"platforms": platforms}).json()["results"]
    ]


def test_a_pick_is_saved_for_the_caller_only(user, other_user) -> None:
    a, b = client_for(user), client_for(other_user)
    pick(a, "karpathy")
    assert names(a) == ["karpathy"]
    assert names(b) == []


def test_the_other_user_picking_the_same_handle_does_not_show_it_to_the_first(
    user, other_user
) -> None:
    a, b = client_for(user), client_for(other_user)
    pick(a, "karpathy")
    pick(b, "sama")
    pick(b, "karpathy")
    assert names(a) == ["karpathy"]
    assert sorted(names(b)) == ["karpathy", "sama"]
    assert SocialHandle.objects.filter(handle_normalized="karpathy").count() == 1
    assert UserSavedHandle.objects.count() == 3


def test_a_handle_known_to_the_cache_is_not_in_anyones_list(user) -> None:
    services.get_or_create_handle(
        "x", "sama", origin=HandleOrigin.LIVE, follower_count=9
    )
    assert names(client_for(user)) == []


def test_picking_twice_keeps_one_saved_row(user) -> None:
    a = client_for(user)
    pick(a, "karpathy")
    pick(a, "Karpathy")
    assert UserSavedHandle.objects.filter(user=user).count() == 1


def test_saved_respects_the_platform(user) -> None:
    a = client_for(user)
    pick(a, "karpathy")
    pick(a, "karpathy", "instagram")
    assert names(a, "x") == ["karpathy"]
    assert names(a, "instagram") == ["karpathy"]
    assert a.get(SAVED, {"platforms": "x,instagram"}).json()["count"] == 2


def test_saved_without_a_token_is_401() -> None:
    response = APIClient(raise_request_exception=False).get(SAVED)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthenticated"


def test_deleting_a_user_deletes_their_list_and_keeps_the_public_handle(user) -> None:
    pick(client_for(user), "karpathy")
    user.delete()
    assert not UserSavedHandle.objects.exists()
    assert SocialHandle.objects.filter(handle_normalized="karpathy").exists()


def test_stats_counts_only_the_callers_saved_handles(user, other_user) -> None:
    pick(client_for(user), "karpathy")
    pick(client_for(other_user), "sama")
    pick(client_for(other_user), "naval")
    body = client_for(user).get("/api/v1/handles/stats").json()
    assert body["saved_handles"] == 1


def test_the_table_keeps_only_the_indexes_something_uses() -> None:
    # uq_user_saved_handle starts with user_id, so it serves every lookup by user; nothing
    # orders by created_at (migration 0009 dropped ix_user_saved_recent and the user_id index).
    with connection.cursor() as cur:
        cur.execute(
            "SELECT indexname FROM pg_indexes WHERE tablename='user_saved_handles'"
        )
        found = {row[0] for row in cur.fetchall()}
    assert "uq_user_saved_handle" in found
    assert "ix_user_saved_recent" not in found
    assert [n for n in found if n.startswith("user_saved_handles_user_id")] == []
