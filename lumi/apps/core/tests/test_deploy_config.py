"""The start commands must run Django under ASGI: SSE needs a server that streams."""

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


def test_railway_starts_and_migrates_with_django_under_uvicorn():
    deploy = json.loads((ROOT / "railway.json").read_text())["deploy"]
    assert "uvicorn config.asgi:application" in deploy["startCommand"]
    assert "app.main" not in deploy["startCommand"]
    assert deploy["preDeployCommand"] == ["uv run python manage.py migrate --noinput"]
    assert deploy["healthcheckPath"] == "/health"


def test_dev_backend_script_uses_the_asgi_application():
    script = json.loads((ROOT / "package.json").read_text())["scripts"]["dev:backend"]
    assert "uvicorn config.asgi:application" in script
    assert "app.main" not in script


@pytest.mark.parametrize("name", ["railway.json", "package.json"])
def test_deploy_files_do_not_mention_the_legacy_app(name):
    assert "app.main" not in (ROOT / name).read_text()
