"""Two requests that create the same account at once must both succeed (React renders twice)."""

from __future__ import annotations

import threading

import httpx
import pytest
from django.db import connection

from apps.accounts.models import User
from apps.connections import accounts
from apps.connections.clients.pfm import PfmClient
from apps.connections.models import ConnectedAccount, PfmLink
from apps.connections.tests.fakes import Recorder, fixture

pytestmark = pytest.mark.django_db(transaction=True)


def test_parallel_pfm_status_calls_create_one_row_and_no_error(monkeypatch) -> None:
    monkeypatch.setenv("PFM_JWT_TOKEN", "pfm-FAKE-JWT")
    user = User.objects.create_user("race@example.com")
    body = fixture("pfm_accounts.json")
    body["data"][0]["external_id"] = "lumi-race-1"
    PfmLink.objects.create(user=user, external_id="lumi-race-1")
    monkeypatch.setattr(
        accounts,
        "make_pfm",
        lambda: PfmClient(
            accounts.get_config(),
            transport=Recorder(lambda r: httpx.Response(200, json=body)).transport,
        ),
    )
    start = threading.Barrier(6)
    errors: list[BaseException] = []

    def work() -> None:
        try:
            start.wait()
            accounts.sync_pfm_accounts(user)
        except BaseException as exc:  # noqa: BLE001 - the test reports whatever the thread hit
            errors.append(exc)
        finally:
            connection.close()

    threads = [threading.Thread(target=work) for _ in range(6)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert errors == []
    assert ConnectedAccount.objects.filter(user=user, provider="pfm").count() == 1
