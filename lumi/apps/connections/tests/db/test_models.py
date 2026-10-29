"""The database, not the service code, enforces the rules of docs/SCHEMA.md section 8."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.db import DataError, IntegrityError, connection, transaction

from apps.connections.models import (
    ConnectedAccount,
    HandleSearchCache,
    HandleSearchCacheEntry,
    McpAuthAccount,
    OAuthState,
    PublishJob,
    XpozCreditLedger,
)
from apps.core.fields import TokenDecryptError, needs_rotation, rotate_value
from apps.profiles.models import SocialHandle, SocialProfile

from .conftest import KEY_A, KEY_B

pytestmark = pytest.mark.django_db

FP = "a" * 64


def raw(sql: str, params: list | None = None):
    with connection.cursor() as cursor:
        cursor.execute(sql, params or [])
        return cursor.fetchall()


def account(user, **kwargs) -> ConnectedAccount:
    defaults = {
        "user": user,
        "provider": "linkedin",
        "external_account_id": "ext-1",
        "access_token": "AT-PLAINTEXT-1",
        "refresh_token": "RT-PLAINTEXT-1",
    }
    return ConnectedAccount.objects.create(**{**defaults, **kwargs})


def test_tokens_round_trip_and_the_table_holds_no_plaintext(user) -> None:
    created = account(user)
    assert ConnectedAccount.objects.get(pk=created.pk).access_token == "AT-PLAINTEXT-1"
    stored = raw("SELECT access_token, refresh_token FROM connected_accounts")[0]
    assert all("PLAINTEXT" not in value for value in stored)
    assert all(value.startswith("gAAAA") for value in stored)


def test_pkce_verifier_is_encrypted_at_rest(user, now) -> None:
    OAuthState.objects.create(
        state="s1",
        user=user,
        provider="x",
        code_verifier="VERIFIER-PLAINTEXT",
        expires_at=now + timedelta(minutes=10),
    )
    (stored,) = raw("SELECT code_verifier FROM oauth_states")[0]
    assert "PLAINTEXT" not in stored


def test_mcp_tokens_are_encrypted_at_rest(user) -> None:
    McpAuthAccount.objects.create(
        user=user,
        account="google",
        access_token="G-PLAINTEXT",
        refresh_token="R-PLAINTEXT",
    )
    stored = raw("SELECT access_token, refresh_token FROM mcp_auth_accounts")[0]
    assert all("PLAINTEXT" not in value for value in stored)


def test_a_token_cannot_be_searched_by_value(user) -> None:
    account(user)
    with pytest.raises(Exception, match="isnull"):
        list(ConnectedAccount.objects.filter(access_token="AT-PLAINTEXT-1"))


def test_rotation_keeps_old_rows_readable_and_a_dropped_key_fails_loudly(
    user, settings
) -> None:
    created = account(user, external_account_id="rotating")
    stale = account(user, external_account_id="stale")
    settings.TOKEN_ENCRYPTION_KEY = KEY_B
    settings.TOKEN_ENCRYPTION_KEY_PREVIOUS = KEY_A
    assert ConnectedAccount.objects.get(pk=created.pk).access_token == "AT-PLAINTEXT-1"

    old_access, old_refresh = raw(
        "SELECT access_token, refresh_token FROM connected_accounts WHERE id = %s",
        [created.pk],
    )[0]
    assert needs_rotation(old_access)
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE connected_accounts SET access_token = %s, refresh_token = %s"
            " WHERE id = %s",
            [rotate_value(old_access), rotate_value(old_refresh), created.pk],
        )

    settings.TOKEN_ENCRYPTION_KEY_PREVIOUS = ""  # the old key is dropped
    assert ConnectedAccount.objects.get(pk=created.pk).access_token == "AT-PLAINTEXT-1"
    with pytest.raises(TokenDecryptError) as info:
        ConnectedAccount.objects.get(pk=stale.pk)  # never rotated
    assert "PLAINTEXT" not in str(info.value)


def test_account_is_unique_per_provider_and_external_id(user, other_user) -> None:
    account(user)
    with pytest.raises(IntegrityError), transaction.atomic():
        account(other_user)


def test_one_account_per_profile_and_provider_but_many_unlinked(user, profile) -> None:
    account(user, external_account_id="a", social_profile=profile)
    account(user, external_account_id="b")
    account(user, external_account_id="c")
    with pytest.raises(IntegrityError), transaction.atomic():
        account(user, external_account_id="d", social_profile=profile)
    account(user, provider="x", external_account_id="e", social_profile=profile)


def test_status_and_provider_are_checked(user) -> None:
    with pytest.raises(IntegrityError), transaction.atomic():
        account(user, status="great")
    with pytest.raises(IntegrityError), transaction.atomic():
        account(user, provider="myspace")
    assert account(user, provider="google").provider == "google"


def test_deleting_the_profile_keeps_the_account_unlinked(user, profile) -> None:
    created = account(user, social_profile=profile)
    SocialProfile.objects.filter(pk=profile.pk).delete()
    created.refresh_from_db()
    assert created.social_profile_id is None


def test_deleting_the_user_removes_their_connections(user, now) -> None:
    account(user)
    OAuthState.objects.create(state="s", user=user, provider="x", expires_at=now)
    user.delete()
    assert ConnectedAccount.objects.count() == 0 and OAuthState.objects.count() == 0


def test_oauth_state_is_unique(user, other_user, now) -> None:
    OAuthState.objects.create(state="same", user=user, provider="x", expires_at=now)
    with pytest.raises(IntegrityError), transaction.atomic():
        OAuthState.objects.create(
            state="same", user=other_user, provider="x", expires_at=now
        )


def job(profile, **kwargs) -> PublishJob:
    defaults = {
        "profile": profile,
        "platform": "linkedin",
        "text": "hola",
        "fingerprint": FP,
        "idempotency_key": "k1",
    }
    return PublishJob.objects.create(**{**defaults, **kwargs})


def test_publish_job_defaults_to_pending_and_a_real_post_id_is_empty(profile) -> None:
    created = job(profile)
    created.refresh_from_db()
    assert created.status == "pending" and created.external_post_id == ""


def test_idempotency_key_is_unique_per_profile_not_global(user, profile) -> None:
    job(profile)
    with pytest.raises(IntegrityError), transaction.atomic():
        job(profile)
    other_handle = SocialHandle.objects.create(
        platform="linkedin", handle_normalized="other"
    )
    other = SocialProfile.objects.create(user=user, handle=other_handle)
    job(other)  # the same key on another profile is fine


@pytest.mark.parametrize("status", ["pending", "done", "failed", "unknown"])
def test_publish_status_accepts_the_four_states(profile, status) -> None:
    job(profile, status=status, idempotency_key=f"k-{status}")


def test_publish_status_rejects_anything_else(profile) -> None:
    with pytest.raises(IntegrityError), transaction.atomic():
        job(profile, status="succeeded")


@pytest.mark.parametrize("fingerprint", ["a" * 63, "a" * 65, "g" * 64, "A" * 64, ""])
def test_fingerprint_must_be_64_lowercase_hex(profile, fingerprint) -> None:
    with pytest.raises((IntegrityError, DataError)), transaction.atomic():
        job(profile, fingerprint=fingerprint)


def test_publish_platform_is_checked(profile) -> None:
    with pytest.raises(IntegrityError), transaction.atomic():
        job(profile, platform="reddit")


def test_deleting_the_account_keeps_the_publish_job(user, profile) -> None:
    created = account(user)
    kept = job(profile, connected_account=created)
    created.delete()
    kept.refresh_from_db()
    assert kept.connected_account_id is None


def test_mcp_account_is_unique_per_user(user, other_user) -> None:
    McpAuthAccount.objects.create(user=user, account="google")
    McpAuthAccount.objects.create(user=other_user, account="google")
    with pytest.raises(IntegrityError), transaction.atomic():
        McpAuthAccount.objects.create(user=user, account="google")


def test_handle_cache_is_unique_per_platform_and_query(db) -> None:
    HandleSearchCache.objects.create(platform="x", query_normalized="kar")
    HandleSearchCache.objects.create(platform="instagram", query_normalized="kar")
    with pytest.raises(IntegrityError), transaction.atomic():
        HandleSearchCache.objects.create(platform="x", query_normalized="kar")


def test_handle_cache_entry_is_unique_and_follows_its_cache(db) -> None:
    cache = HandleSearchCache.objects.create(platform="x", query_normalized="kar")
    handle = SocialHandle.objects.create(platform="x", handle_normalized="karpathy")
    HandleSearchCacheEntry.objects.create(cache=cache, handle=handle)
    with pytest.raises(IntegrityError), transaction.atomic():
        HandleSearchCacheEntry.objects.create(cache=cache, handle=handle)
    cache.delete()
    assert HandleSearchCacheEntry.objects.count() == 0
    assert SocialHandle.objects.filter(pk=handle.pk).exists()


def test_credit_ledger_only_knows_slots_one_and_two(db) -> None:
    XpozCreditLedger.objects.create(route="x.users.search", credits=2, key_slot=2)
    with pytest.raises(IntegrityError), transaction.atomic():
        XpozCreditLedger.objects.create(route="x.users.search", credits=2, key_slot=3)
