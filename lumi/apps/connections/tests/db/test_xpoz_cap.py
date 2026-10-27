"""Xpoz spend is capped per user and globally, across runs. The transport is a mock."""
# ruff: noqa: F401, F811  (fixtures imported from test_handles_api)

from __future__ import annotations

from datetime import timedelta

import httpx
import pytest
from django.utils import timezone

from apps.connections.clients.xpoz import XpozClient
from apps.connections.errors import BudgetExceeded
from apps.connections.models import XpozCreditLedger
from apps.connections.stores import DjangoCreditLedger
from apps.connections.tests.fakes import Recorder, fixture

from .test_handles_api import SEARCH, api, wiring, xpoz

pytestmark = pytest.mark.django_db
# Async tests run the ORM in another thread, so they need real commits (transaction=True).
async_db = pytest.mark.django_db(transaction=True)


@pytest.fixture
def live(monkeypatch):
    monkeypatch.setenv("XPOZ_API_KEY", "k-FAKE")
    monkeypatch.setenv("XPOZ_LIVE_ENABLED", "true")
    monkeypatch.setenv("XPOZ_RUN_CREDIT_BUDGET", "1000")
    return Recorder(lambda r: httpx.Response(200, json=fixture("xpoz_users_x.json")))


def fresh_client(live, user_id: int | None) -> XpozClient:
    """A new client per call, like each chat turn and each HTTP request builds one."""
    from apps.connections.accounts import get_config

    return XpozClient(
        get_config(),
        transport=live.transport,
        ledger=DjangoCreditLedger(user_id),
        run_id="t",
    )


@async_db
async def test_a_new_client_per_run_cannot_reset_the_user_cap(
    user, live, monkeypatch
) -> None:
    monkeypatch.setenv("XPOZ_DAILY_CREDIT_CAP_USER", "4")
    for _ in range(2):  # 2 credits each
        await fresh_client(live, user.id).search_users("x", "naval")
    with pytest.raises(BudgetExceeded):
        await fresh_client(live, user.id).search_users("x", "naval")
    assert len(live.requests) == 2
    assert await XpozCreditLedger.objects.acount() == 2


@async_db
async def test_the_global_cap_is_shared_by_every_user(
    user, other_user, live, monkeypatch
) -> None:
    monkeypatch.setenv("XPOZ_DAILY_CREDIT_CAP_USER", "100")
    monkeypatch.setenv("XPOZ_DAILY_CREDIT_CAP_GLOBAL", "4")
    await fresh_client(live, user.id).search_users("x", "naval")
    await fresh_client(live, other_user.id).search_users("x", "naval")
    with pytest.raises(BudgetExceeded):
        await fresh_client(live, other_user.id).search_users("x", "naval")
    with pytest.raises(BudgetExceeded):
        await fresh_client(live, None).search_users("x", "naval")
    assert len(live.requests) == 2


@async_db
async def test_spend_older_than_a_day_does_not_count(user, live, monkeypatch) -> None:
    monkeypatch.setenv("XPOZ_DAILY_CREDIT_CAP_USER", "2")
    await fresh_client(live, user.id).search_users("x", "naval")
    await XpozCreditLedger.objects.filter(user_id=user.id).aupdate(
        created_at=timezone.now() - timedelta(hours=25)
    )
    await fresh_client(live, user.id).search_users("x", "naval")
    assert len(live.requests) == 2


@async_db
async def test_a_cap_of_zero_blocks_every_live_call(user, live, monkeypatch) -> None:
    monkeypatch.setenv("XPOZ_DAILY_CREDIT_CAP_GLOBAL", "0")
    with pytest.raises(BudgetExceeded):
        await fresh_client(live, user.id).search_users("x", "naval")
    assert live.requests == []


def test_the_search_route_stops_spending_at_the_cap_and_still_answers(
    api, xpoz, monkeypatch
) -> None:
    monkeypatch.setenv("XPOZ_DAILY_CREDIT_CAP_USER", "2")
    first = api.get(SEARCH, {"q": "naval"}).json()
    assert first["live"] is True
    second = api.get(SEARCH, {"q": "elon", "platforms": "x"})
    assert second.status_code == 200
    assert second.json()["reason"] == "budget_exhausted"
    assert len(xpoz.requests) == 1


def test_the_search_route_is_throttled_per_user(api, other_user) -> None:
    from apps.connections.tests.db.test_api import client_for

    for _ in range(30):
        assert api.get(SEARCH, {"q": "n"}).status_code == 200
    assert api.get(SEARCH, {"q": "n"}).status_code == 429
    assert client_for(other_user).get(SEARCH, {"q": "n"}).status_code == 200
