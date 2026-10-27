import pytest
from cryptography.fernet import Fernet
from django.core.exceptions import FieldError, ImproperlyConfigured
from django.db import connection, models

from apps.core import fields
from apps.core.fields import EncryptedTextField, TokenDecryptError

KEY_A = Fernet.generate_key().decode()
KEY_B = Fernet.generate_key().decode()


@pytest.fixture(autouse=True)
def keys(settings):
    settings.TOKEN_ENCRYPTION_KEY = KEY_A
    settings.TOKEN_ENCRYPTION_KEY_PREVIOUS = ""


_MODEL = []


def _secret_class():
    """Defined once per process: redefining an app_label model re-registers it."""
    if not _MODEL:

        class Secret(models.Model):
            token = EncryptedTextField(null=True)

            class Meta:
                app_label = "core"
                db_table = "test_secrets"

        _MODEL.append(Secret)
    return _MODEL[0]


@pytest.fixture
def secret_model(db):
    model = _secret_class()
    with connection.schema_editor() as editor:
        editor.create_model(model)
    yield model
    with connection.schema_editor() as editor:
        editor.delete_model(model)


def raw_value(pk):
    with connection.cursor() as c:
        c.execute("SELECT token FROM test_secrets WHERE id = %s", [pk])
        return c.fetchone()[0]


@pytest.mark.django_db(transaction=True)
def test_round_trip_and_nothing_readable_in_the_table(secret_model):
    row = secret_model.objects.create(token="sk-live-123 ñ")
    stored = raw_value(row.pk)
    assert "sk-live" not in stored and stored.startswith("gAAAA")
    assert secret_model.objects.get(pk=row.pk).token == "sk-live-123 ñ"


@pytest.mark.django_db(transaction=True)
def test_none_and_empty_pass_through(secret_model):
    a = secret_model.objects.create(token=None)
    b = secret_model.objects.create(token="")
    assert raw_value(a.pk) is None and raw_value(b.pk) == ""
    assert secret_model.objects.get(pk=a.pk).token is None
    assert secret_model.objects.get(pk=b.pk).token == ""
    assert secret_model.objects.filter(token__isnull=True).count() == 1


@pytest.mark.django_db(transaction=True)
def test_rotation_reads_old_values_and_rewrites_under_new_key(secret_model, settings):
    row = secret_model.objects.create(token="abc")
    old = raw_value(row.pk)
    settings.TOKEN_ENCRYPTION_KEY = KEY_B
    settings.TOKEN_ENCRYPTION_KEY_PREVIOUS = KEY_A
    assert secret_model.objects.get(pk=row.pk).token == "abc"
    assert fields.needs_rotation(old) is True
    new = fields.rotate_value(old)
    assert fields.needs_rotation(new) is False and fields.decrypt_value(new) == "abc"
    settings.TOKEN_ENCRYPTION_KEY_PREVIOUS = ""
    assert fields.decrypt_value(new) == "abc"
    with pytest.raises(TokenDecryptError):
        fields.decrypt_value(old)


def test_several_previous_keys_are_accepted(settings):
    key_c = Fernet.generate_key().decode()
    old = fields.encrypt_value("x")
    settings.TOKEN_ENCRYPTION_KEY = key_c
    settings.TOKEN_ENCRYPTION_KEY_PREVIOUS = f"{KEY_B}, {KEY_A}"
    assert fields.decrypt_value(old) == "x"


def test_wrong_key_error_carries_no_value(settings):
    stored = fields.encrypt_value("super-secret")
    settings.TOKEN_ENCRYPTION_KEY = KEY_B
    with pytest.raises(TokenDecryptError) as exc:
        fields.decrypt_value(stored)
    assert "super-secret" not in str(exc.value) and stored not in str(exc.value)
    with pytest.raises(TokenDecryptError):
        fields.decrypt_value("not-a-fernet-token")


def test_missing_or_invalid_key_is_a_clear_error_without_echo(settings):
    settings.TOKEN_ENCRYPTION_KEY = ""
    with pytest.raises(ImproperlyConfigured, match="TOKEN_ENCRYPTION_KEY"):
        fields.encrypt_value("x")
    settings.TOKEN_ENCRYPTION_KEY = "not-valid-key-material"
    with pytest.raises(ImproperlyConfigured) as exc:
        fields.encrypt_value("x")
    assert "not-valid-key-material" not in str(exc.value)


def test_each_encryption_differs_so_value_lookups_are_refused():
    assert fields.encrypt_value("same") != fields.encrypt_value("same")
    with pytest.raises(FieldError):
        EncryptedTextField().get_lookup("exact")


def test_interoperates_with_the_connections_token_cipher():
    from apps.connections.crypto import TokenCipher

    cipher = TokenCipher(KEY_A)
    assert fields.decrypt_value(cipher.encrypt("from-connect")) == "from-connect"
    assert cipher.decrypt(fields.encrypt_value("from-core")) == "from-core"
