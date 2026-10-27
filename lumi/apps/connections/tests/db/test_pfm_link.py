"""The PFM sync trusts nothing the remote says about whose account it is."""

from __future__ import annotations

import importlib

import httpx
import pytest
from django.apps import apps as django_apps

from apps.accounts.models import User
from apps.connections import accounts
from apps.connections.clients.pfm import PfmClient
from apps.connections.models import AccountStatus, ConnectedAccount, PfmLink
from apps.connections.tests.fakes import Recorder

pytestmark = pytest.mark.django_db


def acc(id_: str, external_id: str | None, **extra) -> dict:
    return {
        "id": id_,
        "platform": "x",
        "username": id_,
        "status": "connected",
        "external_id": external_id,
        **extra,
    }


@pytest.fixture
def user(db) -> User:
    return User.objects.create_user("owner@example.com")


@pytest.fixture
def pfm(monkeypatch):
    monkeypatch.setenv("PFM_JWT_TOKEN", "pfm-FAKE-JWT")
    rec = Recorder(lambda r: httpx.Response(500))
    client = PfmClient(accounts.get_config(), transport=rec.transport)
    monkeypatch.setattr(accounts, "make_pfm", lambda: client)

    def serve(handler) -> Recorder:
        rec._handler = handler
        return rec

    return serve


def page(rows: list[dict]) -> httpx.Response:
    return httpx.Response(200, json={"data": rows, "meta": {"total": len(rows)}})


def test_a_random_id_per_user_replaces_the_guessable_one(user) -> None:
    other = User.objects.create_user("other@example.com")
    mine = accounts.pfm_external_id(user, create=True)
    theirs = accounts.pfm_external_id(other, create=True)
    assert mine != theirs
    assert mine != f"lumi-user-{user.pk}"
    assert len(mine) >= 20
    assert accounts.pfm_external_id(user, create=True) == mine


def test_a_user_with_nothing_to_sync_asks_pfm_nothing(user, pfm) -> None:
    rec = pfm(lambda r: page([]))
    assert accounts.sync_pfm_accounts(user) == 0
    assert rec.requests == []


def test_accounts_under_another_external_id_are_not_attached(user, pfm) -> None:
    PfmLink.objects.create(user=user, external_id="lumi-mine")
    pfm(
        lambda r: page(
            [
                acc("sa_mine", "lumi-mine"),
                acc("sa_victim", f"lumi-user-{user.pk + 1}"),
                acc("sa_none", None),
            ]
        )
    )
    assert accounts.sync_pfm_accounts(user) == 1
    ids = set(
        ConnectedAccount.objects.filter(provider="pfm").values_list(
            "external_account_id", flat=True
        )
    )
    assert ids == {"sa_mine"}


def test_every_page_is_read(user, pfm) -> None:
    PfmLink.objects.create(user=user, external_id="lumi-mine")
    everything = [acc(f"sa_{i}", "lumi-mine") for i in range(60)]

    def handler(request: httpx.Request) -> httpx.Response:
        offset = int(request.url.params["offset"])
        limit = int(request.url.params["limit"])
        return page(everything[offset : offset + limit])

    pfm(handler)
    assert accounts.sync_pfm_accounts(user) == 60
    assert ConnectedAccount.objects.filter(user=user, provider="pfm").count() == 60


def test_a_user_with_old_rows_and_no_link_keeps_the_legacy_id(user, pfm) -> None:
    ConnectedAccount.objects.create(
        user=user, provider="pfm", external_account_id="sa_old", platform="x"
    )
    rec = pfm(lambda r: page([acc("sa_old", f"lumi-user-{user.pk}")]))
    accounts.sync_pfm_accounts(user)
    assert rec.requests[0].url.params["external_id"] == f"lumi-user-{user.pk}"
    assert PfmLink.objects.get(user=user).external_id == f"lumi-user-{user.pk}"
    row = ConnectedAccount.objects.get(external_account_id="sa_old")
    assert row.status == AccountStatus.ACTIVE


def test_the_migration_gives_existing_pfm_users_their_legacy_id(user) -> None:
    other = User.objects.create_user("none@example.com")
    ConnectedAccount.objects.create(
        user=user, provider="pfm", external_account_id="sa_old", platform="x"
    )
    migration = importlib.import_module("apps.connections.migrations.0006_pfm_links")
    migration.backfill_pfm_links(django_apps, None)
    assert PfmLink.objects.get(user=user).external_id == f"lumi-user-{user.pk}"
    assert not PfmLink.objects.filter(user=other).exists()
