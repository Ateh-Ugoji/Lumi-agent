"""``/api/v1/auth/*``: register, login, logout, me, throttling and the error format."""

from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import AuthToken, User

pytestmark = pytest.mark.django_db

PASSWORD = "correct-horse-battery"


@pytest.fixture
def client():
    return APIClient()


def register(client, email="ana@example.com", password=PASSWORD, **extra):
    return client.post(
        "/api/v1/auth/register",
        {"email": email, "password": password, **extra},
        format="json",
    )


def auth(client, token):
    client.credentials(HTTP_AUTHORIZATION=f"Token {token}")


def test_register_returns_token_and_user(client):
    response = register(client, display_name="Ana")
    assert response.status_code == 201
    body = response.json()
    assert set(body) == {"token", "user"}
    assert body["user"]["email"] == "ana@example.com"
    assert body["user"]["display_name"] == "Ana"
    assert "password" not in body["user"]
    # the stored value is a hash, never the key
    assert not AuthToken.objects.filter(key_hash=body["token"]).exists()
    assert AuthToken.objects.get().key_hash != body["token"]


def test_register_lowercases_the_email(client):
    register(client, email="Ana@Example.COM")
    assert User.objects.get().email == "ana@example.com"


def test_register_rejects_duplicate_email_case_insensitively(client):
    register(client)
    response = register(client, email="ANA@example.com")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"


@pytest.mark.parametrize("password", ["short1", "1234567890123", "password1234"])
def test_register_rejects_weak_passwords(client, password):
    response = register(client, password=password)
    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert "password" in error["details"]
    assert User.objects.count() == 0


def test_register_rejects_bad_email(client):
    response = register(client, email="not-an-email")
    assert response.status_code == 400
    assert "email" in response.json()["error"]["details"]


def test_login_with_right_password(client):
    register(client)
    response = client.post(
        "/api/v1/auth/login",
        {"email": "ANA@example.com", "password": PASSWORD, "device_name": "laptop"},
        format="json",
    )
    assert response.status_code == 200
    assert AuthToken.objects.filter(name="laptop").count() == 1


def test_login_failures_are_indistinguishable(client):
    register(client)
    wrong = client.post(
        "/api/v1/auth/login",
        {"email": "ana@example.com", "password": "nope-nope-nope"},
        format="json",
    )
    unknown = client.post(
        "/api/v1/auth/login",
        {"email": "who@example.com", "password": "nope-nope-nope"},
        format="json",
    )
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()
    assert wrong.json()["error"]["code"] == "unauthenticated"


def test_inactive_user_cannot_log_in(client):
    register(client)
    User.objects.update(is_active=False)
    response = client.post(
        "/api/v1/auth/login",
        {"email": "ana@example.com", "password": PASSWORD},
        format="json",
    )
    assert response.status_code == 401


def test_me_requires_a_token(client):
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthenticated"
    assert response["WWW-Authenticate"] == "Token"


def test_me_with_token(client):
    token = register(client).json()["token"]
    auth(client, token)
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 200
    assert response.json()["email"] == "ana@example.com"


@pytest.mark.parametrize(
    "header", ["Token", "Token a b", "Bearer abc", "Token wrong-key"]
)
def test_bad_authorization_headers(client, header):
    client.credentials(HTTP_AUTHORIZATION=header)
    assert client.get("/api/v1/auth/me").status_code == 401


def test_expired_token_is_rejected(client):
    token = register(client).json()["token"]
    AuthToken.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
    auth(client, token)
    assert client.get("/api/v1/auth/me").status_code == 401


def test_deactivated_user_loses_access(client):
    token = register(client).json()["token"]
    User.objects.update(is_active=False)
    auth(client, token)
    assert client.get("/api/v1/auth/me").status_code == 401


def test_logout_deletes_only_the_token_used(client):
    first = register(client).json()["token"]
    second = client.post(
        "/api/v1/auth/login",
        {"email": "ana@example.com", "password": PASSWORD},
        format="json",
    ).json()["token"]
    auth(client, first)
    assert client.post("/api/v1/auth/logout").status_code == 204
    assert client.get("/api/v1/auth/me").status_code == 401
    auth(client, second)
    assert client.get("/api/v1/auth/me").status_code == 200


def test_last_used_at_is_touched_once_per_hour(client, django_assert_num_queries):
    token = register(client).json()["token"]
    auth(client, token)
    client.get("/api/v1/auth/me")
    first = AuthToken.objects.get().last_used_at
    assert first is not None
    client.get("/api/v1/auth/me")
    assert AuthToken.objects.get().last_used_at == first


def test_login_is_throttled_per_email(client):
    User.objects.create_user("ana@example.com", PASSWORD)
    statuses = [
        client.post(
            "/api/v1/auth/login",
            {"email": "ana@example.com", "password": "bad-bad-bad-bad"},
            format="json",
            REMOTE_ADDR=f"10.0.0.{i}",
        ).status_code
        for i in range(12)
    ]
    assert statuses[:10] == [401] * 10
    assert statuses[10:] == [429, 429]


def test_throttled_response_has_error_format_and_retry_after(client):
    for _ in range(11):
        response = client.post(
            "/api/v1/auth/login",
            {"email": "a@example.com", "password": "x"},
            format="json",
        )
    assert response.status_code == 429
    assert response.json()["error"]["code"] == "rate_limited"
    assert int(response["Retry-After"]) >= 1


def test_malformed_json_is_a_validation_error(client):
    response = client.post(
        "/api/v1/auth/login", data="{not json", content_type="application/json"
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "validation_error"


def test_wrong_method_uses_the_error_format(client):
    response = client.get("/api/v1/auth/login")
    assert response.status_code == 405
    assert response.json()["error"]["code"] == "method_not_allowed"


def test_unknown_route_uses_the_error_format(client):
    response = client.get("/api/v1/nope")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
