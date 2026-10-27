from __future__ import annotations

import httpx
import pytest

from apps.connections import keys as connection_keys
from apps.connections.config import ConnectionsConfig
from apps.connections.providers.registry import build_provider
from apps.core import keys

from .fakes import Recorder


@pytest.fixture(autouse=True)
def empty_registry(monkeypatch):
    monkeypatch.setattr(keys, "_REGISTRY", {})


def test_services_are_registered_and_optional() -> None:
    connection_keys.register_all()
    connection_keys.register_all()  # idempotent
    names = {s.name for s in keys.all_specs()}
    assert {"meta", "linkedin", "x"} <= names
    assert not any(
        s.required for s in keys.all_specs() if s.name in {"meta", "linkedin", "x"}
    )


def test_missing_variables_are_listed_without_values(monkeypatch) -> None:
    monkeypatch.delenv("META_APP_ID", raising=False)
    monkeypatch.setenv("META_APP_SECRET", "super-secret-value")
    connection_keys.register_all()
    spec = keys.get_spec("meta")
    assert keys.missing_variables(spec) == ["META_APP_ID"]
    assert keys.run_probe(spec).status == "skipped"
    assert "super-secret" not in keys.run_probe(spec).detail


def test_x_probe_never_calls_x(monkeypatch) -> None:
    monkeypatch.setenv("X_CLIENT_ID", "id-123456")
    monkeypatch.setenv("X_CLIENT_SECRET", "secret-123456")
    connection_keys.register_all()
    assert keys.run_probe(keys.get_spec("x")).status == "skipped"


async def test_meta_credential_check_uses_client_credentials() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(request.url.params)
        seen["host"] = request.url.host
        return httpx.Response(
            200, json={"access_token": "app-token-FAKE", "token_type": "bearer"}
        )

    rec = Recorder(handler)
    config = ConnectionsConfig.from_env({"META_APP_ID": "1", "META_APP_SECRET": "s"})
    provider = build_provider("meta", config, transport=rec.transport)
    await provider.check_app_credentials()
    assert (
        seen["grant_type"] == "client_credentials"
        and seen["host"] == "graph.facebook.com"
    )


def test_meta_probe_reports_a_rejected_secret_without_the_secret(monkeypatch) -> None:
    from apps.connections.errors import ProviderAuthError

    async def reject(self):
        raise ProviderAuthError(
            "Error validating client secret s3cr3t-value", provider="meta"
        )

    monkeypatch.setattr(
        "apps.connections.providers.meta.MetaProvider.check_app_credentials", reject
    )
    monkeypatch.setenv("META_APP_ID", "1")
    monkeypatch.setenv("META_APP_SECRET", "s3cr3t-value")
    connection_keys.register_all()
    result = keys.run_probe(keys.get_spec("meta"))
    assert result.status == "error" and "s3cr3t" not in result.detail
