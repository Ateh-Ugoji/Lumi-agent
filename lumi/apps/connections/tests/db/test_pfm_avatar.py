"""The photo PFM reports for a connected account refreshes the handle of the linked profile."""

from __future__ import annotations

import httpx
import pytest

from apps.accounts.models import User
from apps.connections import accounts
from apps.connections.clients.pfm import PfmClient
from apps.connections.models import AccountStatus, ConnectedAccount, PfmLink
from apps.connections.tests.fakes import Recorder
from apps.profiles.models import SocialHandle, SocialProfile

pytestmark = pytest.mark.django_db

OLD = "https://img.example/old.jpg"
NEW = "https://img.example/new.jpg"


@pytest.fixture
def user(db) -> User:
    user = User.objects.create_user("owner@example.com")
    PfmLink.objects.create(user=user, external_id="lumi-mine")
    return user


@pytest.fixture
def profile(user) -> SocialProfile:
    handle = SocialHandle.objects.create(
        platform="x", handle_normalized="ateh", avatar_url=OLD
    )
    return SocialProfile.objects.create(user=user, handle=handle)


@pytest.fixture
def pfm(monkeypatch):
    monkeypatch.setenv("PFM_JWT_TOKEN", "pfm-FAKE-JWT")
    rec = Recorder(lambda r: httpx.Response(500))
    client = PfmClient(accounts.get_config(), transport=rec.transport)
    monkeypatch.setattr(accounts, "make_pfm", lambda: client)

    def serve(*, username="Ateh", photo: str | None = NEW, status="connected") -> None:
        body = {
            "id": "sa_1",
            "platform": "x",
            "username": username,
            "status": status,
            "external_id": "lumi-mine",
            "profile_photo_url": photo,
        }
        rec._handler = lambda r: httpx.Response(
            200, json={"data": [body], "meta": {"total": 1}}
        )

    return serve


def link(user, profile, status=AccountStatus.ACTIVE, linked=True) -> None:
    ConnectedAccount.objects.create(
        user=user,
        provider="pfm",
        external_account_id="sa_1",
        platform="x",
        status=status,
        social_profile=profile if linked else None,
    )


def photo() -> str:
    return SocialHandle.objects.get(handle_normalized="ateh").avatar_url


def test_the_photo_of_a_connected_linked_account_refreshes_the_handle(
    user, profile, pfm
) -> None:
    link(user, profile)
    pfm()
    accounts.sync_pfm_accounts(user)
    assert photo() == NEW


@pytest.mark.parametrize("value", [None, ""])
def test_a_missing_photo_changes_nothing(user, profile, pfm, value) -> None:
    link(user, profile)
    pfm(photo=value)
    accounts.sync_pfm_accounts(user)
    assert photo() == OLD


def test_a_photo_that_is_not_a_web_url_changes_nothing(user, profile, pfm) -> None:
    link(user, profile)
    pfm(photo="javascript:alert(1)")
    accounts.sync_pfm_accounts(user)
    assert photo() == OLD


def test_an_account_pfm_reports_disconnected_does_not_touch_the_photo(
    user, profile, pfm
) -> None:
    link(user, profile)
    pfm(status="disconnected")
    accounts.sync_pfm_accounts(user)
    assert ConnectedAccount.objects.get().status == AccountStatus.REVOKED
    assert photo() == OLD


def test_an_account_that_was_not_linked_to_a_profile_does_not_touch_it(
    user, profile, pfm
) -> None:
    link(user, profile, linked=False)
    pfm()
    accounts.sync_pfm_accounts(user)
    assert ConnectedAccount.objects.get().status == AccountStatus.ACTIVE
    assert photo() == OLD


def test_an_account_with_another_username_cannot_repaint_the_handle(
    user, profile, pfm
) -> None:
    """The handle is public. A user who links someone else's account must not change its photo."""
    link(user, profile)
    pfm(username="someone_else")
    accounts.sync_pfm_accounts(user)
    assert photo() == OLD
    assert not SocialHandle.objects.filter(handle_normalized="someone_else").exists()


def test_the_username_may_differ_in_case_and_at_sign(user, profile, pfm) -> None:
    link(user, profile)
    pfm(username="@ATEH")
    accounts.sync_pfm_accounts(user)
    assert photo() == NEW


@pytest.fixture
def calls(monkeypatch) -> list[tuple]:
    seen: list[tuple] = []
    real = accounts.update_profile_avatar

    def spy(profile_id, url, *, username):
        seen.append((profile_id, url, username))
        return real(profile_id, url, username=username)

    monkeypatch.setattr(accounts, "update_profile_avatar", spy)
    return seen


def test_the_service_is_asked_only_for_an_active_linked_account(
    user, profile, pfm, calls
) -> None:
    link(user, profile)
    pfm()
    accounts.sync_pfm_accounts(user)
    assert calls == [(profile.pk, NEW, "Ateh")]


@pytest.mark.parametrize(
    ("status", "linked"),
    [(AccountStatus.ACTIVE, False), (AccountStatus.REVOKED, True)],
)
def test_the_service_is_not_asked_for_a_revoked_or_unlinked_row(
    user, profile, pfm, calls, status, linked
) -> None:
    link(user, profile, linked=linked)
    pfm(status="connected" if status == AccountStatus.ACTIVE else "disconnected")
    accounts.sync_pfm_accounts(user)
    assert calls == []
