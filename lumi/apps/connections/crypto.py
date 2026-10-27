"""Token encryption with key rotation.

Tokens are encrypted with Fernet. ``TOKEN_ENCRYPTION_KEY`` encrypts. Decryption also tries
``TOKEN_ENCRYPTION_KEY_PREVIOUS`` (comma separated for several), so a key can rotate without
downtime: set the new key, move the old one to ``_PREVIOUS``, run ``rotate`` over stored
values, then drop ``_PREVIOUS``.

Legacy. Models use ``apps.core.fields.EncryptedTextField`` (same Fernet format) and nothing
in production code imports this module. It stays only because ARCHITECT's
``apps/core/tests/test_fields.py`` pins the interoperability. Delete both together.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from .errors import ConfigError

KEY_VAR = "TOKEN_ENCRYPTION_KEY"
PREVIOUS_VAR = "TOKEN_ENCRYPTION_KEY_PREVIOUS"


class TokenDecryptError(Exception):
    """The stored value is not valid for any configured key. Carries no value."""


def _fernet(key: str, *, name: str) -> Fernet:
    try:
        return Fernet(key.strip().encode("ascii"))
    except (ValueError, TypeError):
        # Raised without chaining: the original error can echo part of the key.
        raise ConfigError(f"{name} is not a valid Fernet key") from None


class TokenCipher:
    def __init__(self, primary_key: str, previous_keys: Sequence[str] = ()) -> None:
        if not primary_key or not primary_key.strip():
            raise ConfigError(f"{KEY_VAR} is not set")
        self._primary = _fernet(primary_key, name=KEY_VAR)
        previous = [_fernet(k, name=PREVIOUS_VAR) for k in previous_keys if k.strip()]
        self._multi = MultiFernet([self._primary, *previous])

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> TokenCipher:
        previous = [k for k in (env.get(PREVIOUS_VAR) or "").split(",") if k.strip()]
        return cls(env.get(KEY_VAR) or "", previous)

    @staticmethod
    def generate_key() -> str:
        return Fernet.generate_key().decode("ascii")

    def encrypt(self, plaintext: str) -> str:
        return self._multi.encrypt(plaintext.encode("utf-8")).decode("ascii")

    def decrypt(self, ciphertext: str) -> str:
        try:
            return self._multi.decrypt(ciphertext.encode("ascii")).decode("utf-8")
        except (InvalidToken, UnicodeError):
            raise TokenDecryptError(
                "stored value is not decryptable with the configured keys"
            ) from None

    def needs_rotation(self, ciphertext: str) -> bool:
        """True when the value decrypts only with a previous key."""
        try:
            self._primary.decrypt(ciphertext.encode("ascii"))
            return False
        except (InvalidToken, UnicodeError):
            self.decrypt(ciphertext)  # raises TokenDecryptError if no key fits
            return True

    def rotate(self, ciphertext: str) -> str:
        """Re-encrypt under the primary key. Raises ``TokenDecryptError`` if no key fits."""
        try:
            return self._multi.rotate(ciphertext.encode("ascii")).decode("ascii")
        except (InvalidToken, UnicodeError):
            raise TokenDecryptError(
                "stored value is not decryptable with the configured keys"
            ) from None
