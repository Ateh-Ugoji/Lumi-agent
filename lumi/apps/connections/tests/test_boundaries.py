"""Structural rules of the connections core, checked on the source and at runtime."""

from __future__ import annotations

import ast
import dataclasses
from pathlib import Path

import pytest

from apps.connections.config import ConnectionsConfig
from apps.connections.oauth import OAuthStateRecord
from apps.connections.providers.base import AccountInfo, TokenSet
from apps.connections.providers.registry import OAUTH_PROVIDERS, build_provider

PACKAGE = Path(__file__).resolve().parents[1]
FORBIDDEN_ROOTS = {
    "django",
    "rest_framework",
    "fastapi",
    "sqlmodel",
    "sqlalchemy",
    "app",
    "celery",
}


# Django glue. Everything else is the pure core and must not import a web framework.
DJANGO_GLUE = {
    "apps.py",
    "models.py",
    "stores.py",
    "accounts.py",
    "handles_api.py",
    "publish_api.py",
    "mcp_gateway.py",
    "connect_links.py",
    "legacy_import.py",
    "views.py",
    "serializers.py",
    "urls.py",
    "tasks.py",
    "throttles.py",
}


def _sources() -> list[Path]:
    return [
        p for p in PACKAGE.rglob("*.py") if "tests" not in p.relative_to(PACKAGE).parts
    ]


def test_core_does_not_import_a_web_framework_or_the_legacy_backend() -> None:
    offenders = []
    for path in _sources():
        relative = path.relative_to(PACKAGE)
        if (
            relative.parts[0] in {"migrations", "management"}
            or relative.name in DJANGO_GLUE
        ):
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            roots: list[str] = []
            if isinstance(node, ast.Import):
                roots = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                roots = [node.module.split(".")[0]]
            offenders += [f"{path.name}: {r}" for r in roots if r in FORBIDDEN_ROOTS]
    assert offenders == []


def test_only_x_ever_names_x_hosts() -> None:
    for path in _sources():
        text = path.read_text(encoding="utf-8")
        if path.name in {"x.py", "__init__.py"}:
            continue
        assert "api.x.com" not in text, path.name


def test_no_secret_value_is_ever_hardcoded() -> None:
    for path in _sources():
        text = path.read_text(encoding="utf-8")
        assert "AKIA" not in text and "BEGIN PRIVATE KEY" not in text


def test_secret_fields_are_excluded_from_repr() -> None:
    tokens = TokenSet(access_token="AT-SECRET", refresh_token="RT-SECRET")
    account = AccountInfo(external_id="1", display_name="n", access_token="PAGE-SECRET")
    record = OAuthStateRecord(
        state="STATE-SECRET",
        provider="x",
        user_id=1,
        redirect_uri="r",
        redirect_after="/",
        expires_at=None,
        code_verifier="VERIFIER-SECRET",
    )
    text = repr(tokens) + repr(account) + repr(record)
    assert "SECRET" not in text


def test_registry_builds_every_oauth_provider_and_rejects_unknown_names() -> None:
    config = ConnectionsConfig.from_env({})
    for name in OAUTH_PROVIDERS:
        provider = build_provider(name, config)
        assert provider.name == name
        assert provider.capabilities().max_text_length > 0
    with pytest.raises(KeyError):
        build_provider("myspace", config)


def test_value_objects_are_immutable() -> None:
    tokens = TokenSet(access_token="a")
    with pytest.raises(dataclasses.FrozenInstanceError):
        tokens.access_token = "b"  # type: ignore[misc]
