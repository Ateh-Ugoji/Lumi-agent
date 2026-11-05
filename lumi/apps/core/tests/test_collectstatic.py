"""``collectstatic`` runs in the Railway build, where there is no database and no secret key."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parents[3]


def run_collectstatic(tmp_path: Path, **extra: str) -> subprocess.CompletedProcess:
    env_file = tmp_path / "empty.env"
    env_file.write_text("")
    child = {
        "PATH": os.environ["PATH"],
        "LUMI_ENV_FILE": str(env_file),
        "STATIC_ROOT": str(tmp_path / "static"),
        **extra,
    }
    return subprocess.run(
        [sys.executable, "manage.py", "collectstatic", "--noinput"],
        cwd=BASE,
        env=child,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def test_collectstatic_works_with_an_empty_environment_under_prod_settings(tmp_path):
    result = run_collectstatic(tmp_path, DJANGO_SETTINGS_MODULE="config.settings.prod")
    assert result.returncode == 0, result.stderr
    root = tmp_path / "static"
    manifest = json.loads((root / "staticfiles.json").read_text())
    hashed = manifest["paths"]["admin/css/base.css"]
    assert hashed != "admin/css/base.css"
    assert (root / hashed).is_file()
    assert (root / f"{hashed}.gz").is_file()


def test_other_commands_still_demand_database_url(tmp_path):
    env_file = tmp_path / "empty.env"
    env_file.write_text("")
    result = subprocess.run(
        [sys.executable, "manage.py", "migrate", "--check"],
        cwd=BASE,
        env={
            "PATH": os.environ["PATH"],
            "LUMI_ENV_FILE": str(env_file),
            "DJANGO_SETTINGS_MODULE": "config.settings.prod",
        },
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode != 0
    assert "DATABASE_URL" in result.stderr


def test_railway_build_runs_collectstatic_under_prod_settings():
    build = json.loads((BASE / "railway.json").read_text())["build"]
    assert "config.settings.prod" in build["buildCommand"]
    assert "manage.py collectstatic --noinput" in build["buildCommand"]


@pytest.mark.parametrize("name", ["collectstatic"])
def test_collectstatic_is_a_lenient_command(name):
    from apps.core import env

    assert env.is_lenient_invocation(["manage.py", name])
