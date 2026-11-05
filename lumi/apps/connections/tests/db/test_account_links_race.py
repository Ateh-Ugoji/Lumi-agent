"""Parallel links to one profile must end with one account and no server error."""

from __future__ import annotations

import threading

import pytest
from django.db import connection

from apps.accounts.models import User
from apps.connections.account_links import link_account
from apps.connections.models import ConnectedAccount
from apps.profiles.models import SocialHandle, SocialProfile

pytestmark = pytest.mark.django_db(transaction=True)


def test_parallel_links_to_one_profile_leave_exactly_one_account() -> None:
    user = User.objects.create_user("race-link@example.com")
    handle = SocialHandle.objects.create(platform="facebook", handle_normalized="p")
    profile = SocialProfile.objects.create(user=user, handle=handle)
    ids = [f"90{n}" for n in range(6)]
    for ext in ids:
        ConnectedAccount.objects.create(
            user=user,
            provider="meta",
            external_account_id=ext,
            platform="facebook",
            access_token="t",
        )
    start = threading.Barrier(len(ids))
    errors: list[BaseException] = []

    def work(ext: str) -> None:
        try:
            start.wait()
            link_account(user, "meta", account_id=ext, profile=profile)
        except BaseException as exc:  # noqa: BLE001 - the test reports whatever the thread hit
            errors.append(exc)
        finally:
            connection.close()

    threads = [threading.Thread(target=work, args=(ext,)) for ext in ids]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert errors == []
    assert ConnectedAccount.objects.filter(social_profile=profile).count() == 1
