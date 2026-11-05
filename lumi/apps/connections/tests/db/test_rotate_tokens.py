"""``manage.py rotate_tokens``: move every stored secret to the current key."""

from __future__ import annotations

from io import StringIO

import pytest
from cryptography.fernet import Fernet, InvalidToken
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection

from apps.connections.models import ConnectedAccount, McpAuthAccount

from .conftest import KEY_A, KEY_B


def raw_tokens(model, pk) -> tuple[str, str]:
    with connection.cursor() as cursor:
        cursor.execute(
            f"SELECT access_token, refresh_token FROM {model._meta.db_table} WHERE id = %s",
            [pk],
        )
        return cursor.fetchone()


def run(*args: str) -> str:
    out = StringIO()
    call_command("rotate_tokens", *args, stdout=out)
    return out.getvalue()


@pytest.fixture
def old_rows(settings, user):
    """Rows written under KEY_B, then the key moves to KEY_A with KEY_B kept as previous."""
    settings.TOKEN_ENCRYPTION_KEY = KEY_B
    account = ConnectedAccount.objects.create(
        user=user,
        provider="meta",
        external_account_id="m-1",
        access_token="plain-access-1",
        refresh_token="plain-refresh-1",
    )
    grant = McpAuthAccount.objects.create(
        user=user, account="google", access_token="g-access", refresh_token="g-refresh"
    )
    settings.TOKEN_ENCRYPTION_KEY = KEY_A
    settings.TOKEN_ENCRYPTION_KEY_PREVIOUS = KEY_B
    return account, grant


def opens_with(key: str, ciphertext: str) -> bool:
    try:
        Fernet(key.encode()).decrypt(ciphertext.encode())
        return True
    except InvalidToken:
        return False


def test_every_secret_ends_up_under_the_current_key(old_rows) -> None:
    account, grant = old_rows
    assert opens_with(KEY_B, raw_tokens(ConnectedAccount, account.pk)[0])
    out = run()
    for model, row in ((ConnectedAccount, account), (McpAuthAccount, grant)):
        for value in raw_tokens(model, row.pk):
            assert opens_with(KEY_A, value) and not opens_with(KEY_B, value)
    assert "'rotated': 4" in out  # two secrets in each of two rows
    assert "plain-access-1" not in out and "g-refresh" not in out


def test_values_still_read_the_same_after_the_rotation(old_rows, settings) -> None:
    account, grant = old_rows
    run()
    settings.TOKEN_ENCRYPTION_KEY_PREVIOUS = ""  # the old key can go now
    assert (
        ConnectedAccount.objects.get(pk=account.pk).refresh_token == "plain-refresh-1"
    )
    assert McpAuthAccount.objects.get(pk=grant.pk).access_token == "g-access"


def test_a_second_run_changes_nothing(old_rows) -> None:
    run()
    assert "'rotated': 0" in run()


def test_a_dry_run_writes_nothing(old_rows) -> None:
    account, _ = old_rows
    before = raw_tokens(ConnectedAccount, account.pk)
    out = run("--dry-run")
    assert raw_tokens(ConnectedAccount, account.pk) == before
    assert "dry run" in out and "'rotated': 4" in out


def test_a_value_no_key_opens_is_listed_and_fails_the_run(old_rows, settings) -> None:
    account, _ = old_rows
    settings.TOKEN_ENCRYPTION_KEY_PREVIOUS = ""  # the old key was dropped too early
    out = StringIO()
    with pytest.raises(CommandError, match="TOKEN_ENCRYPTION_KEY_PREVIOUS"):
        call_command("rotate_tokens", stdout=out)
    assert f"unreadable ids: {account.pk}" in out.getvalue()
    # Nothing was destroyed: the old key still opens it.
    assert opens_with(KEY_B, raw_tokens(ConnectedAccount, account.pk)[0])


def test_a_row_a_request_changed_meanwhile_is_skipped_not_overwritten(
    old_rows, monkeypatch
) -> None:
    from apps.connections.management.commands import rotate_tokens

    account, _grant = old_rows
    real = rotate_tokens.rotate_value
    raced = []

    def rotate_then_lose_the_race(ciphertext):
        fresh = real(ciphertext)
        if not raced:
            raced.append(True)
            ConnectedAccount.objects.filter(pk=account.pk).update(
                access_token="written-by-a-request"
            )
        return fresh

    monkeypatch.setattr(rotate_tokens, "rotate_value", rotate_then_lose_the_race)
    run()
    assert (
        ConnectedAccount.objects.get(pk=account.pk).access_token
        == "written-by-a-request"
    )
