"""Startup behaviour seen from outside: a fresh process with a controlled environment.

These run ``manage.py`` in a subprocess so the settings module is imported for real. No test
here reads or prints a key; the child environment is built from scratch.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parents[3]
URL = "postgresql://u:pw-not-real@localhost:5432/lumi"
SECRET = "x" * 40
FERNET = (
    "ZmFrZS1mYWtlLWZha2UtZmFrZS1mYWtlLWZha2UtMDA="  # shape only; not used to encrypt
)


def run(*args, env=None, env_file=None):
    child = {"PATH": os.environ["PATH"], "HOME": os.environ.get("HOME", "/tmp")}
    child["LUMI_ENV_FILE"] = str(env_file) if env_file else "/nonexistent/.env"
    child.update(env or {})
    return subprocess.run(
        [sys.executable, "manage.py", *args],
        cwd=BASE,
        env=child,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def test_every_command_fails_clearly_without_database_url():
    result = run("check")
    assert result.returncode != 0
    assert "DATABASE_URL" in result.stderr + result.stdout
    assert "sqlite" not in (result.stderr + result.stdout).lower().replace(
        "no hay sqlite", ""
    )


def test_sqlite_url_is_refused():
    result = run(
        "check", env={"DATABASE_URL": "sqlite:///lumi.db", "SECRET_KEY": SECRET}
    )
    assert result.returncode != 0
    assert "SQLite" in result.stderr + result.stdout


def test_missing_secret_key_fails_clearly():
    result = run("check", env={"DATABASE_URL": URL})
    assert result.returncode != 0
    assert "SECRET_KEY" in result.stderr + result.stdout


def test_settings_read_the_env_file(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(f"DATABASE_URL={URL}\nSECRET_KEY={SECRET}\n")
    result = run("check", env_file=env_file)
    assert result.returncode == 0, result.stderr


def test_real_environment_wins_over_the_env_file(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(f"DATABASE_URL={URL}\nSECRET_KEY={SECRET}\n")
    result = run("check", env={"DATABASE_URL": "sqlite:///x.db"}, env_file=env_file)
    assert result.returncode != 0


def test_check_keys_works_with_an_empty_environment_and_reports_what_is_missing():
    result = run("check_keys", "--json")
    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    report = {row["name"]: row for row in payload["services"]}
    for name in ("database", "secret", "token_encryption"):
        assert report[name]["required"] and report[name]["status"] == "error"
    optional = [row for row in report.values() if not row["required"]]
    assert optional and all(row["status"] == "skipped" for row in optional)


def test_check_keys_never_echoes_a_configured_value(tmp_path):
    env_file = tmp_path / ".env"
    marker = "sk-marker-should-never-be-printed-123456"
    env_file.write_text(
        f"DATABASE_URL={URL}\nSECRET_KEY={marker}\nTOKEN_ENCRYPTION_KEY=not-a-key-{marker}\n"
    )
    result = run("check_keys", "--only", "secret,token_encryption", env_file=env_file)
    assert marker not in result.stdout + result.stderr


def test_optional_services_are_warned_not_fatal(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        f"DATABASE_URL={URL}\nSECRET_KEY={SECRET}\nTOKEN_ENCRYPTION_KEY={FERNET}\nGROQ_API_KEY=dummy-not-called\n"
    )
    code = (
        "import os, django, logging, io\n"
        "os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.dev')\n"
        "buf = io.StringIO(); logging.getLogger('lumi.keys').addHandler(logging.StreamHandler(buf))\n"
        "django.setup()\n"
        "from apps.core import startup\n"
        "startup.check()\n"
        "print('WARNED' if 'META_APP_ID' in buf.getvalue() else 'SILENT')\n"
    )
    child = {
        "PATH": os.environ["PATH"],
        "LUMI_ENV_FILE": str(env_file),
        "DJANGO_SETTINGS_MODULE": "config.settings.dev",
    }
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=BASE,
        env=child,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "WARNED" in result.stdout


@pytest.mark.live
def test_check_keys_live_every_configured_service_answers():
    """Runs every registered probe with the keys in lumi/.env. ``LUMI_RUN_LIVE=1 pytest -m live``."""
    import io

    from django.core.management import call_command

    out = io.StringIO()
    call_command("check_keys", "--json", stdout=out)
    rows = json.loads(out.getvalue())["services"]
    failed = [f"{r['name']}: {r['detail']}" for r in rows if r["status"] == "error"]
    assert not failed, "; ".join(failed)
