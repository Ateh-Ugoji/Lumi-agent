"""/api/schema/ and /api/docs/: public with DEBUG=True, staff only with DEBUG=False."""

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import AuthToken, User

pytestmark = pytest.mark.django_db

URLS = ["/api/schema/?format=json", "/api/docs/"]


@pytest.fixture
def staff():
    return User.objects.create_user(
        "ops@example.com", "correct-horse-battery", is_staff=True
    )


@pytest.mark.parametrize("url", URLS)
def test_public_in_debug(settings, url):
    settings.DEBUG = True
    assert APIClient().get(url).status_code == 200


def test_debug_schema_declares_token_auth(settings):
    settings.DEBUG = True
    schemes = (
        APIClient()
        .get("/api/schema/?format=json")
        .json()["components"]["securitySchemes"]
    )
    assert schemes["tokenAuth"]["name"] == "Authorization"


@pytest.mark.parametrize("url", URLS)
def test_anonymous_is_refused_in_production(settings, url):
    settings.DEBUG = False
    response = APIClient().get(url)
    assert response.status_code == 401
    if url.startswith("/api/schema/"):
        assert response.json()["error"]["code"] == "unauthenticated"


@pytest.mark.parametrize("url", URLS)
def test_regular_user_is_refused_in_production(settings, url):
    settings.DEBUG = False
    user = User.objects.create_user("ana@example.com", "correct-horse-battery")
    client = APIClient()
    client.force_authenticate(user)
    assert client.get(url).status_code == 403


@pytest.mark.parametrize("url", URLS)
def test_staff_session_from_the_admin_login_is_accepted(settings, staff, url):
    settings.DEBUG = False
    client = APIClient()
    client.force_login(staff)
    assert client.get(url).status_code == 200


@pytest.mark.parametrize("url", URLS)
def test_staff_token_is_accepted(settings, staff, url):
    settings.DEBUG = False
    _, key = AuthToken.issue(staff)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Token {key}")
    assert client.get(url).status_code == 200


def test_inactive_staff_session_is_refused(settings, staff):
    settings.DEBUG = False
    client = APIClient()
    client.force_login(staff)
    User.objects.filter(pk=staff.pk).update(is_active=False)
    assert client.get("/api/schema/?format=json").status_code in {401, 403}
