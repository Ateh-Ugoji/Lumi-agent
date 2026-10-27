"""Fixtures shared by the API tests of every app."""

import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from apps.accounts.models import AuthToken, User
from apps.profiles import services
from apps.profiles.models import SocialProfile


def client_for(user: User) -> APIClient:
    _, key = AuthToken.issue(user, name="tests")
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Token {key}")
    return client


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def owner(db):
    return User.objects.create_user("owner@example.com")


@pytest.fixture
def stranger(db):
    return User.objects.create_user("stranger@example.com")


@pytest.fixture
def api(owner):
    return client_for(owner)


@pytest.fixture
def stranger_api(stranger):
    return client_for(stranger)


@pytest.fixture
def make_profile(db):
    def make(user, handle="ateh", platform="x"):
        hid = services.get_or_create_handle(platform, handle, origin="profile")
        return SocialProfile.objects.create(user=user, handle_id=hid)

    return make


@pytest.fixture
def profile(owner, make_profile):
    return make_profile(owner)
