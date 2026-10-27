"""Build a synthetic legacy ``lumi.db`` from the frozen fixtures next to this file.

``legacy_schema.sql`` is the legacy schema and ``legacy_rows.sql`` a small set of rows
that cover every merge and skip rule of the importer. Loading them needs no legacy code,
so these tests survive the removal of ``lumi/app/``. ``legacy_regen.py`` rebuilds both
files from the legacy models while those still exist.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

HERE = Path(__file__).parent


def dt(day: int, hour: int = 12) -> datetime:
    return datetime(2026, 1, day, hour, tzinfo=UTC)


def build_legacy_db(path: Path, *, populate=True) -> Path:
    conn = sqlite3.connect(path)
    try:
        conn.executescript((HERE / "legacy_schema.sql").read_text())
        if populate:
            conn.executescript((HERE / "legacy_rows.sql").read_text())
        conn.commit()
    finally:
        conn.close()
    return path
