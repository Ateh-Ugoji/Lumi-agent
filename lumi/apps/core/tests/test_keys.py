import pytest
from django.core.exceptions import ImproperlyConfigured

from apps.core import keys
from apps.core.probes import probe_token_encryption


@pytest.fixture
def clean_registry(monkeypatch):
    monkeypatch.setattr(keys, "_REGISTRY", {})


def test_validate_required_lists_all_missing_at_once(clean_registry, monkeypatch):
    for var in ("AAA_KEY", "BBB_KEY", "CCC_KEY"):
        monkeypatch.delenv(var, raising=False)
    keys.register(keys.KeySpec("a", ("AAA_KEY",), required=True))
    keys.register(keys.KeySpec("b", ("BBB_KEY",), required=True))
    keys.register(keys.KeySpec("c", ("CCC_KEY",), required=False))
    with pytest.raises(ImproperlyConfigured) as exc:
        keys.validate_required()
    assert "AAA_KEY" in str(exc.value) and "BBB_KEY" in str(exc.value)
    assert "CCC_KEY" not in str(exc.value)


def test_optional_missing_warns_without_values(clean_registry, monkeypatch, caplog):
    monkeypatch.delenv("OPT_KEY", raising=False)
    keys.register(keys.KeySpec("opt", ("OPT_KEY",)))
    with caplog.at_level("WARNING", logger="lumi.keys"):
        keys.warn_optional()
    assert "OPT_KEY" in caplog.text


def test_register_same_name_with_other_definition_fails(clean_registry):
    keys.register(keys.KeySpec("x", ("X1",)))
    with pytest.raises(ImproperlyConfigured):
        keys.register(keys.KeySpec("x", ("X2",)))


def test_scrub_removes_configured_values(clean_registry, monkeypatch):
    monkeypatch.setenv("SOME_API_KEY", "super-secret-value-123")
    keys.register(keys.KeySpec("s", ("SOME_API_KEY",)))
    assert "super-secret" not in keys.scrub("error with super-secret-value-123 inside")


def test_token_encryption_probe(monkeypatch):
    from cryptography.fernet import Fernet

    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    assert probe_token_encryption().status == "ok"
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", "not-a-key")
    result = probe_token_encryption()
    assert result.status == "failed"
    assert "not-a-key" not in result.detail


def test_core_registers_its_services():
    names = {spec.name for spec in keys.all_specs()}
    assert {"database", "secret", "token_encryption"} <= names
