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
        seen.update(httpx.QueryParams(request.content.decode()))
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


def test_pfm_and_xpoz_are_registered_and_optional() -> None:
    connection_keys.register_all()
    specs = {s.name: s for s in keys.all_specs()}
    assert {"pfm", "xpoz"} <= set(specs)
    assert not specs["pfm"].required and not specs["xpoz"].required
    assert specs["pfm"].env_vars == ("PFM_JWT_TOKEN",)
    assert specs["xpoz"].env_vars == ("XPOZ_API_KEY",)


def test_pfm_without_a_token_does_not_probe(monkeypatch) -> None:
    monkeypatch.delenv("PFM_JWT_TOKEN", raising=False)

    async def boom(self, **kw):
        raise AssertionError("must not call PFM")

    monkeypatch.setattr(
        "apps.connections.clients.pfm.PfmClient.list_social_accounts", boom
    )
    connection_keys.register_all()
    result = keys.run_probe(keys.get_spec("pfm"))
    assert result.status in {"skipped", "error"} and "PFM_JWT_TOKEN" in result.detail


def test_pfm_probe_reports_a_rejected_token_without_the_token(monkeypatch) -> None:
    from apps.connections.errors import ProviderAuthError

    async def reject(self, **kw):
        raise ProviderAuthError("bad token pfm-s3cr3t-token", provider="pfm")

    monkeypatch.setattr(
        "apps.connections.clients.pfm.PfmClient.list_social_accounts", reject
    )
    monkeypatch.setenv("PFM_JWT_TOKEN", "pfm-s3cr3t-token")
    connection_keys.register_all()
    result = keys.run_probe(keys.get_spec("pfm"))
    assert result.status == "error" and "s3cr3t" not in result.detail


def test_pfm_probe_ok_uses_one_read_through_the_mock(monkeypatch) -> None:
    calls: list[dict] = []

    async def fine(self, **kw):
        calls.append(kw)
        return []

    monkeypatch.setattr(
        "apps.connections.clients.pfm.PfmClient.list_social_accounts", fine
    )
    monkeypatch.setenv("PFM_JWT_TOKEN", "t")
    connection_keys.register_all()
    assert keys.run_probe(keys.get_spec("pfm")).status == "ok" and calls == [
        {"limit": 1}
    ]


def test_xpoz_probe_never_touches_the_network_or_spends_credits(monkeypatch) -> None:
    async def boom(*a, **kw):
        raise AssertionError("check_keys must not spend Xpoz credits")

    monkeypatch.setattr("apps.connections.clients.xpoz.XpozClient._get", boom)
    monkeypatch.setattr("httpx.AsyncClient.send", boom)
    monkeypatch.setenv("XPOZ_API_KEY", "xp-s3cr3t")
    monkeypatch.setenv("XPOZ_LIVE_ENABLED", "true")
    connection_keys.register_all()
    result = keys.run_probe(keys.get_spec("xpoz"))
    assert result.status == "skipped" and "s3cr3t" not in result.detail
    assert "1 key" in result.detail and "créditos" in result.detail


def _google_probe(monkeypatch, handler):
    real = httpx.AsyncClient
    monkeypatch.setattr(
        "apps.connections.keys.httpx.AsyncClient",
        lambda **kw: real(transport=httpx.MockTransport(handler), **kw),
    )
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "g-id")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "g-s3cr3t")
    connection_keys.register_all()
    return keys.run_probe(keys.get_spec("google"))


def test_google_is_registered_and_optional() -> None:
    connection_keys.register_all()
    spec = keys.get_spec("google")
    assert not spec.required
    assert spec.env_vars == ("GOOGLE_OAUTH_CLIENT_ID", "GOOGLE_OAUTH_CLIENT_SECRET")


def test_google_probe_accepts_a_client_that_rejects_only_the_code(monkeypatch) -> None:
    seen = []

    def handler(request):
        seen.append(request.url.host)
        return httpx.Response(400, json={"error": "invalid_grant"})

    assert _google_probe(monkeypatch, handler).status == "ok"
    assert seen == ["oauth2.googleapis.com"]


def test_google_probe_rejects_a_bad_client_without_the_secret(monkeypatch) -> None:
    result = _google_probe(
        monkeypatch,
        lambda r: httpx.Response(401, json={"error": "invalid_client"}),
    )
    assert result.status == "error" and "s3cr3t" not in result.detail


def test_google_probe_survives_an_outage(monkeypatch) -> None:
    def down(request):
        raise httpx.ConnectError("boom g-s3cr3t")

    result = _google_probe(monkeypatch, down)
    assert result.status == "error" and "s3cr3t" not in result.detail
