"""``/api/v1/services`` and ``/api/v1/service-credentials``: staff only, and the secret never leaves."""

from __future__ import annotations

import logging

import pytest
from django.db import connection
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.connections.models import Service, ServiceCredential

from .test_api import client_for

pytestmark = pytest.mark.django_db

SECRET = "SECRET-PLAINTEXT-0123456789"
URL = "/api/v1/service-credentials"


@pytest.fixture
def staff(db) -> User:
    return User.objects.create_user("staff@example.com", is_staff=True)


@pytest.fixture
def staff_api(staff) -> APIClient:
    return client_for(staff)


def body(**kwargs) -> dict:
    return {
        "service": "meta",
        "app_id": "123456789",
        "app_secret": SECRET,
        "label": "dev",
        "environment": "development",
        **kwargs,
    }


def raw(sql: str):
    with connection.cursor() as cursor:
        cursor.execute(sql)
        return cursor.fetchall()


def create(client: APIClient, **kwargs):
    return client.post(URL, body(**kwargs), format="json")


# --- who can call --------------------------------------------------------------------------


def test_every_route_needs_a_token() -> None:
    anon = APIClient()
    for method, url in [
        ("get", "/api/v1/services"),
        ("get", URL),
        ("post", URL),
        ("get", f"{URL}/1"),
        ("patch", f"{URL}/1"),
        ("delete", f"{URL}/1"),
    ]:
        assert getattr(anon, method)(url).status_code == 401, (method, url)


def test_a_user_who_is_not_staff_is_refused_everywhere(user) -> None:
    client = client_for(user)
    for method, url in [
        ("get", "/api/v1/services"),
        ("get", URL),
        ("post", URL),
        ("get", f"{URL}/1"),
        ("patch", f"{URL}/1"),
        ("delete", f"{URL}/1"),
    ]:
        assert getattr(client, method)(url).status_code == 403, (method, url)


def test_debug_mode_does_not_open_the_routes_to_a_normal_user(user, settings) -> None:
    settings.DEBUG = True  # IsStaffOrDebug would let this through; IsStaff must not
    assert client_for(user).get(URL).status_code == 403


def test_a_normal_user_cannot_create_anything(user) -> None:
    assert create(client_for(user)).status_code == 403
    assert ServiceCredential.objects.count() == 0


# --- catalog -------------------------------------------------------------------------------


def test_staff_reads_the_catalog(staff_api) -> None:
    response = staff_api.get("/api/v1/services")
    assert response.status_code == 200
    rows = {row["code"]: row for row in response.json()["services"]}
    assert set(rows) == {"pfm", "meta", "linkedin", "x", "google", "xpoz", "youtube"}
    assert rows["youtube"]["is_active"] is False
    assert rows["meta"]["auth_type"] == "oauth2"


def test_the_catalog_is_read_only_over_http(staff_api) -> None:
    assert staff_api.post("/api/v1/services", {}, format="json").status_code == 405


# --- create --------------------------------------------------------------------------------


def test_create_stores_an_encrypted_secret_and_never_returns_it(staff_api, staff) -> None:
    response = create(staff_api)
    assert response.status_code == 201
    assert SECRET not in response.content.decode()
    data = response.json()
    assert "app_secret" not in data
    assert data["service"] == "meta" and data["service_name"] == "Meta (Facebook Pages)"
    assert data["app_id"] == "123456789"
    assert data["secret_hint"] == SECRET[-4:] and data["has_secret"] is True
    assert data["updated_by"] == staff.pk
    (stored,) = raw("SELECT app_secret FROM service_credentials")[0]
    assert "PLAINTEXT" not in stored and stored.startswith("gAAAA")
    assert ServiceCredential.objects.get(pk=data["id"]).app_secret == SECRET


def test_the_answer_is_never_cached(staff_api) -> None:
    assert create(staff_api)["Cache-Control"] == "no-store"
    assert staff_api.get(URL)["Cache-Control"] == "no-store"


def test_create_validates_the_body(staff_api) -> None:
    for bad in (
        {"service": "nope"},
        {"service": None},
        {"app_secret": ""},
        {"app_secret": "x" * 2001},
        {"environment": "staging"},
        {"extra": ["not", "an", "object"]},
        {"extra": {"client_secret": "x"}},
        {"label": "x" * 61},
    ):
        response = create(staff_api, **bad)
        assert response.status_code == 400, bad
        assert response.json()["error"]["code"] == "validation_error", bad
        assert SECRET not in response.content.decode(), bad
    assert ServiceCredential.objects.count() == 0


def test_the_secret_is_required_on_create(staff_api) -> None:
    payload = body()
    del payload["app_secret"]
    assert staff_api.post(URL, payload, format="json").status_code == 400


def test_an_api_key_service_needs_no_app_id(staff_api) -> None:
    response = create(staff_api, service="pfm", app_id="")
    assert response.status_code == 201
    assert response.json()["app_id"] == ""


def test_a_second_active_credential_for_the_same_service_and_environment_is_a_409(
    staff_api,
) -> None:
    assert create(staff_api).status_code == 201
    response = create(staff_api, label="again")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "credentials.conflict"
    assert ServiceCredential.objects.count() == 1


def test_an_inactive_or_other_environment_credential_is_allowed(staff_api) -> None:
    assert create(staff_api).status_code == 201
    assert create(staff_api, label="old", is_active=False).status_code == 201
    assert create(staff_api, label="live", environment="production").status_code == 201


def test_extra_keeps_plain_settings(staff_api) -> None:
    extra = {"redirect_uri": "http://localhost:3010/connections/meta/callback"}
    assert create(staff_api, extra=extra).json()["extra"] == extra


# --- read ----------------------------------------------------------------------------------


def test_list_filters_and_never_carries_a_secret(staff_api) -> None:
    create(staff_api)
    create(staff_api, service="pfm", app_id="", app_secret="PFM-TOKEN-PLAINTEXT-ABCDEF")
    create(staff_api, label="live", environment="production")
    everything = staff_api.get(URL)
    assert everything.status_code == 200
    assert "PLAINTEXT" not in everything.content.decode()
    assert len(everything.json()["credentials"]) == 3
    only_meta = staff_api.get(URL, {"service": "meta"}).json()["credentials"]
    assert {row["service"] for row in only_meta} == {"meta"} and len(only_meta) == 2
    only_prod = staff_api.get(URL, {"environment": "production"}).json()["credentials"]
    assert [row["label"] for row in only_prod] == ["live"]
    assert staff_api.get(URL, {"environment": "staging"}).status_code == 400


def test_list_with_the_active_filter(staff_api) -> None:
    create(staff_api)
    create(staff_api, label="old", is_active=False)
    active = staff_api.get(URL, {"active": "true"}).json()["credentials"]
    assert [row["label"] for row in active] == ["dev"]
    inactive = staff_api.get(URL, {"active": "false"}).json()["credentials"]
    assert [row["label"] for row in inactive] == ["old"]


def test_detail_and_unknown_id(staff_api) -> None:
    pk = create(staff_api).json()["id"]
    one = staff_api.get(f"{URL}/{pk}")
    assert one.status_code == 200 and SECRET not in one.content.decode()
    assert staff_api.get(f"{URL}/999999").status_code == 404


# --- update --------------------------------------------------------------------------------


def test_patch_without_a_secret_keeps_the_stored_one(staff_api) -> None:
    pk = create(staff_api).json()["id"]
    response = staff_api.patch(f"{URL}/{pk}", {"label": "renamed"}, format="json")
    assert response.status_code == 200 and response.json()["label"] == "renamed"
    row = ServiceCredential.objects.get(pk=pk)
    assert row.app_secret == SECRET and row.secret_hint == SECRET[-4:]


def test_patch_with_a_new_secret_replaces_it_and_the_hint(staff_api) -> None:
    pk = create(staff_api).json()["id"]
    new = "A-BRAND-NEW-SECRET-VALUE-9876"
    response = staff_api.patch(f"{URL}/{pk}", {"app_secret": new}, format="json")
    assert response.status_code == 200
    assert new not in response.content.decode()
    assert response.json()["secret_hint"] == "9876"
    assert ServiceCredential.objects.get(pk=pk).app_secret == new


def test_patch_cannot_blank_the_secret_or_move_the_service(staff_api) -> None:
    pk = create(staff_api).json()["id"]
    assert staff_api.patch(f"{URL}/{pk}", {"app_secret": ""}, format="json").status_code == 400
    moved = staff_api.patch(f"{URL}/{pk}", {"service": "x"}, format="json")
    assert moved.status_code == 400
    assert ServiceCredential.objects.get(pk=pk).service.code == "meta"
    assert ServiceCredential.objects.get(pk=pk).app_secret == SECRET


def test_patch_that_collides_with_the_active_one_is_a_409(staff_api) -> None:
    create(staff_api)
    other = create(staff_api, label="old", is_active=False).json()["id"]
    response = staff_api.patch(f"{URL}/{other}", {"is_active": True}, format="json")
    assert response.status_code == 409
    assert ServiceCredential.objects.get(pk=other).is_active is False


def test_patch_records_who_changed_it(staff_api) -> None:
    pk = create(staff_api).json()["id"]
    second = User.objects.create_user("second@example.com", is_staff=True)
    response = client_for(second).patch(f"{URL}/{pk}", {"label": "x"}, format="json")
    assert response.json()["updated_by"] == second.pk


# --- delete --------------------------------------------------------------------------------


def test_delete_removes_the_credential_but_not_the_service(staff_api) -> None:
    pk = create(staff_api).json()["id"]
    assert staff_api.delete(f"{URL}/{pk}").status_code == 204
    assert staff_api.get(f"{URL}/{pk}").status_code == 404
    assert staff_api.delete(f"{URL}/{pk}").status_code == 404
    assert Service.objects.filter(code="meta").exists()


# --- secrets stay out of logs and errors ---------------------------------------------------


def test_the_audit_log_names_fields_but_never_values(staff_api, caplog) -> None:
    caplog.set_level(logging.INFO, logger="apps.connections.service_credentials")
    pk = create(staff_api).json()["id"]
    staff_api.patch(f"{URL}/{pk}", {"app_secret": "ANOTHER-PLAINTEXT-SECRET-1234"}, format="json")
    staff_api.delete(f"{URL}/{pk}")
    text = caplog.text
    assert "created" in text and "updated" in text and "deleted" in text
    assert "app_secret" in text  # the field NAME is fine
    assert "PLAINTEXT" not in text and "123456789" not in text


def test_the_secret_is_hidden_from_debug_error_pages(staff_api) -> None:
    response = create(staff_api)
    # Django's error reporter masks the parameters the request lists here.
    assert response.wsgi_request.sensitive_post_parameters == ("app_secret",)


def test_the_throttle_limits_a_burst(staff_api, settings) -> None:
    from rest_framework.throttling import SimpleRateThrottle

    from apps.connections.throttles import ServiceCredentialThrottle

    ServiceCredentialThrottle.rate = "3/min"
    try:
        # ``get_rate`` is read at construction; refresh the parsed values.
        codes = []
        for _ in range(5):
            codes.append(staff_api.get(URL).status_code)
        assert codes[:3] == [200, 200, 200] and 429 in codes[3:]
    finally:
        ServiceCredentialThrottle.rate = "30/min"
        assert issubclass(ServiceCredentialThrottle, SimpleRateThrottle)
