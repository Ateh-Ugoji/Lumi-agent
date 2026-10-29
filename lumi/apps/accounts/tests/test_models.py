from datetime import timedelta

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.accounts.models import AuthToken, User

pytestmark = pytest.mark.django_db


def test_create_user_lowercases_email_and_hashes_password():
    user = User.objects.create_user("  Ada@Example.COM ", "s3cret-pass")
    assert user.email == "ada@example.com"
    assert user.password != "s3cret-pass"
    assert user.check_password("s3cret-pass")
    assert User.objects.get_by_natural_key("ADA@example.com").pk == user.pk


def test_email_is_unique_regardless_of_case():
    User.objects.create_user("ada@example.com")
    with pytest.raises(IntegrityError), transaction.atomic():
        User.objects.create_user("Ada@Example.com")


def test_database_rejects_mixed_case_email_written_around_the_manager():
    with pytest.raises(IntegrityError), transaction.atomic():
        User.objects.bulk_create([User(email="Mixed@Example.com")])


def test_timestamps_are_filled_by_the_database():
    user = User.objects.create_user("t@example.com")
    assert user.created_at is not None and user.updated_at is not None


def test_token_stores_only_the_hash_and_authenticates():
    user = User.objects.create_user("t@example.com")
    row, key = AuthToken.issue(user, name="cli")
    assert key not in row.key_hash and len(row.key_hash) == 64
    found = AuthToken.lookup(key)
    assert found is not None and found.user_id == user.pk
    assert AuthToken.lookup(key + "x") is None


def test_expired_token_and_inactive_user_are_rejected():
    user = User.objects.create_user("t@example.com")
    row, key = AuthToken.issue(user)
    AuthToken.objects.filter(pk=row.pk).update(
        expires_at=timezone.now() - timedelta(seconds=1)
    )
    assert AuthToken.lookup(key) is None
    _, key2 = AuthToken.issue(user)
    User.objects.filter(pk=user.pk).update(is_active=False)
    assert AuthToken.lookup(key2) is None


def test_token_ttl_defaults_to_30_days():
    user = User.objects.create_user("t@example.com")
    row, _ = AuthToken.issue(user)
    delta = row.expires_at - timezone.now()
    assert timedelta(days=29, hours=23) < delta <= timedelta(days=30)
