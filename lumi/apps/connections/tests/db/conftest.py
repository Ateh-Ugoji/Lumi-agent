"""Tests in this folder use the real Postgres tables. They need no provider key and no network."""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet
from django.utils import timezone

from apps.accounts.models import User
from apps.profiles.models import SocialHandle, SocialProfile

KEY_A = Fernet.generate_key().decode()
KEY_B = Fernet.generate_key().decode()


@pytest.fixture(autouse=True)
def encryption_keys(settings) -> None:
    settings.TOKEN_ENCRYPTION_KEY = KEY_A
    settings.TOKEN_ENCRYPTION_KEY_PREVIOUS = ""


@pytest.fixture
def user(db) -> User:
    return User.objects.create_user("owner@example.com")


@pytest.fixture
def other_user(db) -> User:
    return User.objects.create_user("other@example.com")


@pytest.fixture
def profile(user) -> SocialProfile:
    handle = SocialHandle.objects.create(platform="linkedin", handle_normalized="me")
    return SocialProfile.objects.create(user=user, handle=handle)


@pytest.fixture
def now():
    return timezone.now()
