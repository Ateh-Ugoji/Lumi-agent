"""Start Django for the browser e2e: a clean database, simulated providers, no real key.

    . /workspace/lumi-connect/devenv.sh
    uv run python e2e/server.py          # http://localhost:8000

Needs DATABASE_URL (a local Postgres, see scripts/dev_postgres.py). It drops and recreates the
database ``lumi_e2e`` next to it on every start. The environment is rebuilt from scratch, so a key
in your shell can never reach a provider from here.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[1]
E2E_DB = "lumi_e2e"
KEEP = ("PATH", "HOME", "LANG", "TMPDIR", "SECRET_KEY", "TOKEN_ENCRYPTION_KEY")


def _database_urls() -> tuple[str, str]:
    raw = os.environ.get("DATABASE_URL")
    if not raw:
        sys.exit("Falta DATABASE_URL. Corre `. devenv.sh` o scripts/dev_postgres.py.")
    parts = urlsplit(raw)
    return (
        urlunsplit(parts._replace(path="/postgres")),
        urlunsplit(parts._replace(path=f"/{E2E_DB}")),
    )


def _recreate_database(admin_url: str) -> None:
    import psycopg

    with psycopg.connect(admin_url, autocommit=True) as conn:
        conn.execute(f'DROP DATABASE IF EXISTS "{E2E_DB}" WITH (FORCE)')
        conn.execute(f'CREATE DATABASE "{E2E_DB}"')


def main() -> None:
    admin_url, e2e_url = _database_urls()
    kept = {k: os.environ[k] for k in KEEP if k in os.environ}
    os.environ.clear()
    os.environ.update(kept)
    os.environ.update(
        {
            "DATABASE_URL": e2e_url,
            "DJANGO_SETTINGS_MODULE": "e2e.settings",
            "PUBLIC_BASE_URL": "http://localhost:8000",
            "FRONTEND_URL": "http://localhost:3010",
            "META_APP_ID": "e2e-meta-app",
            "META_APP_SECRET": "e2e-meta-secret",
            "PFM_JWT_TOKEN": "e2e-pfm-token",
        }
    )
    sys.path.insert(0, str(ROOT))
    _recreate_database(admin_url)

    import django

    django.setup()
    from django.core.management import call_command

    call_command("migrate", verbosity=0)
    from apps.core import agent_runtime
    from e2e import sim

    sim.install()
    agent_runtime.set_runtime(sim.FakeRuntime())
    port = os.environ.get("E2E_PORT", "8000")
    call_command("runserver", f"127.0.0.1:{port}", use_reloader=False, verbosity=1)


if __name__ == "__main__":
    main()
