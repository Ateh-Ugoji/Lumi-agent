"""``EncryptedTextField``: text encrypted at rest with Fernet and key rotation.

``TOKEN_ENCRYPTION_KEY`` encrypts. ``TOKEN_ENCRYPTION_KEY_PREVIOUS`` (comma separated) is tried on
read, so a key rotates without downtime: set the new key, move the old one to ``_PREVIOUS``, run
``rotate_value`` over the stored rows (``manage.py rotate_tokens`` in a later task), drop ``_PREVIOUS``.

The ciphertext is a standard Fernet token, the same format as ``apps.connections.crypto.TokenCipher``,
so values written by one are readable by the other.

Limits, by design: the column cannot be filtered or ordered by value (each encryption is different),
and a value that no configured key opens raises ``TokenDecryptError`` without carrying the value.
"""

from __future__ import annotations

from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django.conf import settings
from django.core.exceptions import FieldError, ImproperlyConfigured
from django.db import models

KEY_SETTING = "TOKEN_ENCRYPTION_KEY"
PREVIOUS_SETTING = "TOKEN_ENCRYPTION_KEY_PREVIOUS"


class TokenDecryptError(Exception):
    """The stored value is not valid for any configured key. Carries no value."""


def _split(raw: str) -> tuple[str, ...]:
    return tuple(k.strip() for k in (raw or "").split(",") if k.strip())


@lru_cache(maxsize=8)
def _build(primary: str, previous: tuple[str, ...]) -> tuple[Fernet, MultiFernet]:
    try:
        first = Fernet(primary.encode("ascii"))
        rest = [Fernet(k.encode("ascii")) for k in previous]
    except (ValueError, TypeError, UnicodeError):
        # No chaining: the original error can echo part of a key.
        raise ImproperlyConfigured(
            f"{KEY_SETTING} o {PREVIOUS_SETTING} no es una clave Fernet válida."
        ) from None
    return first, MultiFernet([first, *rest])


def _ciphers() -> tuple[Fernet, MultiFernet]:
    primary = (getattr(settings, KEY_SETTING, "") or "").strip()
    if not primary:
        raise ImproperlyConfigured(
            f"Falta {KEY_SETTING}. Genera una con: python -c "
            '"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
        )
    return _build(primary, _split(getattr(settings, PREVIOUS_SETTING, "")))


def encrypt_value(plaintext: str) -> str:
    return _ciphers()[1].encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_value(ciphertext: str) -> str:
    try:
        return _ciphers()[1].decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except (InvalidToken, UnicodeError):
        raise TokenDecryptError(
            "El valor guardado no se puede descifrar con las claves configuradas."
        ) from None


def needs_rotation(ciphertext: str) -> bool:
    """True when the value opens only with a previous key."""
    primary, _ = _ciphers()
    try:
        primary.decrypt(ciphertext.encode("ascii"))
        return False
    except (InvalidToken, UnicodeError):
        decrypt_value(ciphertext)  # raises TokenDecryptError if no key fits
        return True


def rotate_value(ciphertext: str) -> str:
    """Re-encrypt under the primary key."""
    try:
        return _ciphers()[1].rotate(ciphertext.encode("ascii")).decode("ascii")
    except (InvalidToken, UnicodeError):
        raise TokenDecryptError(
            "El valor guardado no se puede descifrar con las claves configuradas."
        ) from None


class EncryptedTextField(models.TextField):
    """Python side holds plaintext; the database holds a Fernet token. ``None`` and ``""`` pass through."""

    description = "Text encrypted at rest"

    def from_db_value(self, value, expression, connection):
        if value is None or value == "":
            return value
        return decrypt_value(value)

    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        if value is None or value == "":
            return value
        return encrypt_value(value)

    def get_lookup(self, lookup_name):
        if lookup_name != "isnull":
            raise FieldError(
                "Un campo cifrado solo admite el filtro isnull, no se puede buscar por valor."
            )
        return super().get_lookup(lookup_name)
