"""X retires a refresh token the moment it issues the next one.

If the write that stores the new pair fails, the old pair is dead and the new one only lived
in memory. These tests pin what is done about that.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from django.db import DatabaseError, connection

from apps.connections import accounts
from apps.connections.models import AccountStatus, ConnectedAccount
from apps.connections.providers.base import TokenSet


class RotatingX:
    name = "x"

    async def refresh(self, tokens: TokenSet) -> TokenSet:
        return TokenSet(
            access_token="new-access",
            refresh_token="new-refresh",
            expires_at=datetime.now(UTC) + timedelta(hours=2),
        )


@pytest.fixture
def x_row(user) -> ConnectedAccount:
    return ConnectedAccount.objects.create(
        user=user,
        provider="x",
        external_account_id="x-1",
        access_token="old-access",
        refresh_token="old-refresh",
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )


def failing_saves(monkeypatch, times: int) -> list[int]:
    """Make the first ``times`` writes of the token columns fail like a dropped connection."""
    calls: list[int] = []
    real_save = ConnectedAccount.save

    def save(self, *args, **kwargs):
        fields = kwargs.get("update_fields") or []
        if "refresh_token" in fields:
            calls.append(1)
            if len(calls) <= times:
                # A real failed statement: Postgres aborts the transaction it ran in.
                with connection.cursor() as cursor:
                    cursor.execute("SELECT 1 / 0")
                raise DatabaseError("unreachable")
        return real_save(self, *args, **kwargs)

    monkeypatch.setattr(ConnectedAccount, "save", save)
    return calls


def stored(row: ConnectedAccount) -> ConnectedAccount:
    return ConnectedAccount.objects.get(pk=row.pk)


def test_a_failed_save_is_retried_and_the_rotated_token_is_kept(
    x_row, monkeypatch
) -> None:
    calls = failing_saves(monkeypatch, times=1)
    outcome = accounts.refresh_account(x_row.pk, factory=lambda _: RotatingX())
    assert outcome == "refreshed" and len(calls) == 2
    row = stored(x_row)
    assert (row.access_token, row.refresh_token) == ("new-access", "new-refresh")
    assert row.status == AccountStatus.ACTIVE and row.last_error == ""


def test_when_both_saves_fail_the_account_asks_for_a_reconnect(
    x_row, monkeypatch
) -> None:
    calls = failing_saves(monkeypatch, times=2)
    outcome = accounts.refresh_account(x_row.pk, factory=lambda _: RotatingX())
    assert outcome == "save_failed" and len(calls) == 2
    row = stored(x_row)
    assert row.status == AccountStatus.ERROR
    assert row.last_error == accounts.REFRESH_NOT_SAVED


def test_one_lost_save_does_not_stop_the_other_accounts(
    user, x_row, monkeypatch
) -> None:
    other = ConnectedAccount.objects.create(
        user=user,
        provider="x",
        external_account_id="x-2",
        access_token="old-access",
        refresh_token="old-refresh",
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )
    failing_saves(monkeypatch, times=2)
    monkeypatch.setattr(accounts, "make_provider", lambda _: RotatingX())
    counts = accounts.refresh_due()
    assert counts == {"save_failed": 1, "refreshed": 1}
    states = sorted((stored(r).status, stored(r).refresh_token) for r in (x_row, other))
    assert states == [
        (AccountStatus.ACTIVE, "new-refresh"),
        (AccountStatus.ERROR, "old-refresh"),
    ]


def test_the_retry_writes_only_the_token_columns(x_row, monkeypatch) -> None:
    seen: list[list[str]] = []
    real_save = ConnectedAccount.save

    def save(self, *args, **kwargs):
        seen.append(list(kwargs.get("update_fields") or ["<all>"]))
        return real_save(self, *args, **kwargs)

    monkeypatch.setattr(ConnectedAccount, "save", save)
    accounts.refresh_account(x_row.pk, factory=lambda _: RotatingX())
    assert seen and "<all>" not in seen[-1]
    assert "refresh_token" in seen[-1] and "status" not in seen[-1]


def test_publishing_asks_for_a_reconnect_when_the_new_tokens_were_lost(
    x_row, monkeypatch
) -> None:
    from apps.connections import publish_api
    from apps.core.errors import ApiError

    failing_saves(monkeypatch, times=2)
    monkeypatch.setattr(accounts, "make_provider", lambda _: RotatingX())
    x_row.expires_at = datetime.now(UTC) + timedelta(seconds=5)
    x_row.save()
    with pytest.raises(ApiError) as caught:
        publish_api.fresh_row(x_row)
    assert caught.value.api_code == "publish.reconnect_required"
