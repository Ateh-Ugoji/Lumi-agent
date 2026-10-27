from __future__ import annotations

import pytest

from apps.connections.config import ConfigError
from apps.connections.crypto import TokenCipher, TokenDecryptError

SECRET = "ya29.a0-a-very-secret-access-token"


def test_round_trip_and_ciphertext_hides_plaintext() -> None:
    cipher = TokenCipher(TokenCipher.generate_key())
    stored = cipher.encrypt(SECRET)
    assert SECRET not in stored
    assert "secret" not in stored
    assert cipher.decrypt(stored) == SECRET


def test_encryption_is_not_deterministic() -> None:
    cipher = TokenCipher(TokenCipher.generate_key())
    assert cipher.encrypt(SECRET) != cipher.encrypt(SECRET)


def test_unicode_and_empty_values_round_trip() -> None:
    cipher = TokenCipher(TokenCipher.generate_key())
    for value in ("", "señal-ñandú-✓"):
        assert cipher.decrypt(cipher.encrypt(value)) == value


def test_rotation_keeps_old_values_readable_and_reencrypts() -> None:
    old_key, new_key = TokenCipher.generate_key(), TokenCipher.generate_key()
    stored_with_old = TokenCipher(old_key).encrypt(SECRET)

    rotating = TokenCipher(new_key, [old_key])
    assert rotating.decrypt(stored_with_old) == SECRET
    assert rotating.needs_rotation(stored_with_old) is True

    rotated = rotating.rotate(stored_with_old)
    assert rotating.needs_rotation(rotated) is False
    # After the old key is dropped, only the new key is needed.
    assert TokenCipher(new_key).decrypt(rotated) == SECRET
    with pytest.raises(TokenDecryptError):
        TokenCipher(new_key).decrypt(stored_with_old)


def test_value_under_unknown_key_is_rejected_without_leaking() -> None:
    stored = TokenCipher(TokenCipher.generate_key()).encrypt(SECRET)
    other = TokenCipher(TokenCipher.generate_key())
    with pytest.raises(TokenDecryptError) as info:
        other.decrypt(stored)
    assert SECRET not in str(info.value)
    with pytest.raises(TokenDecryptError):
        other.needs_rotation(stored)
    with pytest.raises(TokenDecryptError):
        other.rotate(stored)


def test_tampered_or_garbage_ciphertext_is_rejected() -> None:
    cipher = TokenCipher(TokenCipher.generate_key())
    stored = cipher.encrypt(SECRET)
    flipped = stored[:-4] + ("AAAA" if not stored.endswith("AAAA") else "BBBB")
    with pytest.raises(TokenDecryptError):
        cipher.decrypt(flipped)
    with pytest.raises(TokenDecryptError):
        cipher.decrypt("not-a-token")
    with pytest.raises(TokenDecryptError):
        cipher.decrypt("ñ")  # non-ASCII must not raise UnicodeEncodeError


def test_missing_or_malformed_key_fails_loudly_without_echoing_it() -> None:
    with pytest.raises(ConfigError):
        TokenCipher("")
    with pytest.raises(ConfigError):
        TokenCipher.from_env({})
    bad = "not-a-fernet-key-but-sensitive"
    with pytest.raises(ConfigError) as info:
        TokenCipher(bad)
    assert bad not in str(info.value)
    assert info.value.__cause__ is None
    with pytest.raises(ConfigError):
        TokenCipher(TokenCipher.generate_key(), [bad])


def test_from_env_reads_several_previous_keys() -> None:
    k1, k2, k3 = (TokenCipher.generate_key() for _ in range(3))
    env = {"TOKEN_ENCRYPTION_KEY": k3, "TOKEN_ENCRYPTION_KEY_PREVIOUS": f"{k2}, {k1},"}
    cipher = TokenCipher.from_env(env)
    assert cipher.decrypt(TokenCipher(k1).encrypt("a")) == "a"
    assert cipher.decrypt(TokenCipher(k2).encrypt("b")) == "b"
    assert TokenCipher(k3).decrypt(cipher.encrypt("c")) == "c"
