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
    keys.register("a", required=True, env_vars=("AAA_KEY",))
    keys.register("b", required=True, env_vars=("BBB_KEY",))
    keys.register("c", env_vars=("CCC_KEY",))
    with pytest.raises(ImproperlyConfigured) as exc:
        keys.validate_required()
    assert "AAA_KEY" in str(exc.value) and "BBB_KEY" in str(exc.value)
    assert "CCC_KEY" not in str(exc.value)


def test_optional_missing_warns_without_values(clean_registry, monkeypatch, caplog):
    monkeypatch.delenv("OPT_KEY", raising=False)
    keys.register("opt", env_vars=("OPT_KEY",))
    with caplog.at_level("WARNING", logger="lumi.keys"):
        keys.warn_optional()
    assert "OPT_KEY" in caplog.text


def test_register_same_name_with_other_definition_fails(clean_registry):
    keys.register("x", env_vars=("X1",))
    with pytest.raises(ImproperlyConfigured):
        keys.register("x", env_vars=("X2",))


def test_scrub_removes_configured_values(clean_registry, monkeypatch):
    monkeypatch.setenv("SOME_API_KEY", "super-secret-value-123")
    keys.register("s", env_vars=("SOME_API_KEY",))
    assert "super-secret" not in keys.scrub("error with super-secret-value-123 inside")


def test_token_encryption_probe(monkeypatch):
    from cryptography.fernet import Fernet

    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    assert probe_token_encryption().status == "ok"
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", "not-a-key")
    result = probe_token_encryption()
    assert result.status == "error"
    assert "not-a-key" not in result.detail


def test_core_registers_its_services():
    names = {spec.name for spec in keys.all_specs()}
    assert {"database", "secret", "token_encryption"} <= names


def test_run_probe_skips_optional_and_errors_required(clean_registry, monkeypatch):
    monkeypatch.delenv("OPT_KEY", raising=False)
    monkeypatch.delenv("REQ_KEY", raising=False)
    opt = keys.register(
        "opt", lambda: pytest.fail("no debe llamarse"), env_vars=("OPT_KEY",)
    )
    req = keys.register(
        "req",
        lambda: pytest.fail("no debe llamarse"),
        required=True,
        env_vars=("REQ_KEY",),
    )
    assert keys.run_probe(opt).status == "skipped"
    assert keys.run_probe(req).status == "error"


def test_run_probe_handles_async_and_exceptions_without_leaking(
    clean_registry, monkeypatch
):
    monkeypatch.setenv("SVC_KEY", "abcdefgh-secret-12345")

    async def good():
        return keys.ProbeResult("svc", "ok", "listo abcdefgh-secret-12345")

    def bad():
        raise RuntimeError("abcdefgh-secret-12345")

    ok = keys.run_probe(keys.register("svc", good, env_vars=("SVC_KEY",)))
    assert ok.status == "ok" and "abcdefgh" not in ok.detail
    boom = keys.run_probe(keys.register("boom", bad, env_vars=("SVC_KEY",)))
    assert boom.status == "error" and "abcdefgh" not in boom.detail


def test_check_keys_command_exit_codes(monkeypatch, capsys):
    from django.core.management import call_command

    monkeypatch.delenv("TOKEN_ENCRYPTION_KEY", raising=False)
    with pytest.raises(SystemExit) as exc:
        call_command("check_keys", only="token_encryption")
    assert exc.value.code == 1
    assert "TOKEN_ENCRYPTION_KEY" in capsys.readouterr().out
