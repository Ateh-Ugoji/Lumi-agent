"""``services`` and ``service_credentials``: the database enforces the rules, the secret is encrypted."""

from __future__ import annotations

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
from django.db.models import ProtectedError

from apps.connections.models import Provider, Service, ServiceCredential

pytestmark = pytest.mark.django_db

SECRET = "SECRET-PLAINTEXT-0123456789"


def raw(sql: str, params: list | None = None):
    with connection.cursor() as cursor:
        cursor.execute(sql, params or [])
        return cursor.fetchall()


def credential(code: str = "meta", **kwargs) -> ServiceCredential:
    defaults = {
        "service": Service.objects.get(code=code),
        "app_id": "123456789",
        "app_secret": SECRET,
        "label": "dev",
    }
    return ServiceCredential.objects.create(**{**defaults, **kwargs})


def test_the_catalog_is_seeded_by_the_migration() -> None:
    codes = set(Service.objects.values_list("code", flat=True))
    assert codes == {"pfm", "meta", "linkedin", "x", "google", "xpoz", "youtube"}


def test_every_provider_that_connects_accounts_is_in_the_catalog() -> None:
    assert {p.value for p in Provider} <= set(Service.objects.values_list("code", flat=True))


def test_youtube_is_listed_but_off_until_it_has_an_adapter() -> None:
    assert Service.objects.get(code="youtube").is_active is False
    assert Service.objects.get(code="meta").is_active is True


def test_service_codes_are_unique() -> None:
    with pytest.raises(IntegrityError), transaction.atomic():
        Service.objects.create(code="x", name="Dup", kind="social", auth_type="oauth2")


@pytest.mark.parametrize(
    "bad",
    [{"kind": "other"}, {"auth_type": "password"}],
)
def test_the_database_refuses_unknown_kinds_and_auth_types(bad) -> None:
    fields = {"code": "new", "name": "New", "kind": "social", "auth_type": "oauth2", **bad}
    with pytest.raises(IntegrityError), transaction.atomic():
        Service.objects.create(**fields)


def test_the_secret_round_trips_and_the_table_holds_no_plaintext() -> None:
    created = credential()
    assert ServiceCredential.objects.get(pk=created.pk).app_secret == SECRET
    (stored,) = raw("SELECT app_secret FROM service_credentials")[0]
    assert "PLAINTEXT" not in stored
    assert stored.startswith("gAAAA")


def test_the_app_id_is_plain_text_because_it_is_not_a_secret() -> None:
    credential()
    assert raw("SELECT app_id FROM service_credentials") == [("123456789",)]


def test_the_hint_is_the_last_four_characters_of_a_long_secret() -> None:
    created = credential()
    assert ServiceCredential.objects.get(pk=created.pk).secret_hint == SECRET[-4:]


@pytest.mark.parametrize("short", ["", "abc123", "x" * 11])
def test_a_short_or_empty_secret_gets_no_hint(short) -> None:
    created = credential(app_secret=short)
    assert ServiceCredential.objects.get(pk=created.pk).secret_hint == ""


def test_saving_only_the_secret_still_refreshes_the_hint() -> None:
    created = credential()
    created.app_secret = "A-NEW-LONG-SECRET-VALUE-9876"
    created.save(update_fields=["app_secret"])
    assert ServiceCredential.objects.get(pk=created.pk).secret_hint == "9876"


def test_one_active_credential_per_service_and_environment() -> None:
    credential(environment="development")
    with pytest.raises(IntegrityError), transaction.atomic():
        credential(environment="development", label="again")


def test_an_inactive_one_and_another_environment_do_not_collide() -> None:
    credential(environment="development")
    credential(environment="development", is_active=False, label="old")
    credential(environment="production", label="live")
    assert ServiceCredential.objects.filter(service__code="meta").count() == 3


def test_the_database_refuses_an_unknown_environment() -> None:
    with pytest.raises(IntegrityError), transaction.atomic():
        credential(environment="staging")


def test_an_api_key_service_keeps_its_key_in_the_secret_and_no_app_id() -> None:
    created = credential("pfm", app_id="", app_secret="PFM-TOKEN-PLAINTEXT-ABCDEF")
    assert ServiceCredential.objects.get(pk=created.pk).app_id == ""
    (stored,) = raw("SELECT app_secret FROM service_credentials")[0]
    assert "PLAINTEXT" not in stored


def test_defaults_come_from_the_database() -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO service_credentials (service_id) "
            "SELECT id FROM services WHERE code = 'xpoz'"
        )
    row = ServiceCredential.objects.get(service__code="xpoz")
    assert (row.app_id, row.app_secret, row.label, row.secret_hint) == ("", "", "", "")
    assert row.environment == "development" and row.is_active is True
    assert row.extra == {} and row.last_check_ok is None
    assert row.created_at is not None and row.updated_at is not None


def test_a_service_with_credentials_cannot_be_deleted() -> None:
    credential()
    with pytest.raises(ProtectedError):
        Service.objects.get(code="meta").delete()


def test_the_string_form_never_carries_the_secret_or_the_app_id() -> None:
    text = str(credential())
    assert text == "meta:development:dev"
    assert SECRET not in text and "123456789" not in text


@pytest.mark.parametrize(
    "key", ["client_secret", "access_token", "Password", "api_key", "private_key"]
)
def test_extra_rejects_keys_that_look_like_secrets(key) -> None:
    created = credential(extra={key: "x"})
    with pytest.raises(ValidationError):
        created.clean()


def test_extra_accepts_plain_settings() -> None:
    created = credential(
        extra={"redirect_uri": "http://localhost:3010/connections/meta/callback", "graph_version": "v26.0"}
    )
    created.clean()


def test_the_secret_never_appears_in_a_model_repr() -> None:
    created = credential()
    assert SECRET not in repr(created) and SECRET not in str(created.__dict__.get("service", ""))


def test_the_secret_column_is_covered_by_key_rotation() -> None:
    from apps.connections.management.commands.rotate_tokens import encrypted_columns

    assert any(
        table == "service_credentials" and column == "app_secret"
        for _label, table, _pk, column in encrypted_columns()
    )
