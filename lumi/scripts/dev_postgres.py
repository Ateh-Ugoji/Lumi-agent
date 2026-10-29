#!/usr/bin/env python
"""Start a real local PostgreSQL with pgserver and print its DATABASE_URL.

Usage:
    uv run python scripts/dev_postgres.py            # data in lumi/.pgdata, database "lumi"
    uv run python scripts/dev_postgres.py --test     # also creates the "lumi_test" database
    LUMI_PGDATA=/ruta uv run python scripts/dev_postgres.py

The server keeps running after this script exits. Stdout is only the URL, so you can do:
    export DATABASE_URL=$(uv run python scripts/dev_postgres.py)
Messages go to stderr. The URL uses a Unix socket and carries no password.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

DB_NAME = "lumi"
TEST_DB_NAME = "lumi_test"


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--test", action="store_true", help=f"also create the {TEST_DB_NAME} database"
    )
    args = parser.parse_args()

    try:
        import pgserver
    except ImportError:
        sys.stderr.write(
            "Falta pgserver. Corre `uv sync` dentro de lumi/ (está en el grupo dev).\n"
        )
        return 1

    pgdata = Path(
        os.environ.get("LUMI_PGDATA") or Path(__file__).resolve().parents[1] / ".pgdata"
    )
    server = pgserver.get_server(pgdata, cleanup_mode=None)

    names = [DB_NAME] + ([TEST_DB_NAME] if args.test else [])
    for name in names:
        exists = server.psql(f"SELECT 1 FROM pg_database WHERE datname = '{name}';")
        if "1 row" not in exists:
            server.psql(f"CREATE DATABASE {name};")
            sys.stderr.write(f"Base creada: {name}\n")

    sys.stderr.write(f"Postgres listo en {pgdata}\n")
    sys.stdout.write(server.get_uri(DB_NAME) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
