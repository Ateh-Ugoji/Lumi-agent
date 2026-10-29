"""Regression tests for the partial voice-profile index on SQLite (blueprint-fix B-2).

`uq_voice_profiles_current_per_profile` was declared with `postgresql_where` only.
SQLite ignores that dialect-scoped kwarg, so the index degenerated to a plain
`UNIQUE(profile_id)`: one voice-profile row per profile, which makes the versioned
voice-profile design (flip the old row, insert the new current row) fail locally
with IntegrityError even when the ordering is correct.

The tests migrate a **fresh** SQLite database with alembic — the real schema a
machine gets — instead of SQLModel metadata, so they fail if either the model's
`sqlite_where` or the migration regresses.
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
INDEX_NAME = "uq_voice_profiles_current_per_profile"


@pytest.fixture(scope="module")
def migrated_db(tmp_path_factory: pytest.TempPathFactory) -> Path:
    db_path = tmp_path_factory.mktemp("voice_index") / "migrated.db"
    env = {**os.environ, "DATABASE_URL": f"sqlite+aiosqlite:///{db_path}"}
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"alembic upgrade failed:\n{result.stdout}\n{result.stderr}"
    return db_path


def _connect(db_path: Path) -> sqlite3.Connection:
    return sqlite3.connect(db_path)


def _insert_profile(conn: sqlite3.Connection, key: str) -> int:
    cursor = conn.execute(
        "INSERT INTO profiles (name, platform, handle, pfm_account_id, created_at) "
        "VALUES ('Test', 'x', ?, ?, '2026-01-01 00:00:00')",
        (f"handle_{key}", f"spc_{key}"),
    )
    assert cursor.lastrowid is not None
    return int(cursor.lastrowid)


def _insert_voice(conn: sqlite3.Connection, profile_id: int, version: int, is_current: bool) -> None:
    conn.execute(
        "INSERT INTO voice_profiles "
        "(profile_id, version, is_current, payload, example_post_ids, created_at) "
        "VALUES (?, ?, ?, '{}', '[]', '2026-01-01 00:00:00')",
        (profile_id, version, int(is_current)),
    )


def test_migrated_index_is_partial(migrated_db: Path) -> None:
    conn = _connect(migrated_db)
    row = conn.execute("SELECT sql FROM sqlite_master WHERE name = ?", (INDEX_NAME,)).fetchone()
    assert row is not None, "the voice current-profile index is missing from the migrated schema"
    assert "WHERE IS_CURRENT = 1" in str(row[0]).upper(), (
        "index must be partial (WHERE is_current = 1), not a plain UNIQUE(profile_id)"
    )


def test_second_voice_profile_version_can_be_inserted(migrated_db: Path) -> None:
    conn = _connect(migrated_db)
    profile_id = _insert_profile(conn, "version_flip")
    _insert_voice(conn, profile_id, 1, is_current=True)
    # the documented versioning order: flip the old row, then insert the new one
    conn.execute(
        "UPDATE voice_profiles SET is_current = 0 WHERE profile_id = ? AND version = 1",
        (profile_id,),
    )
    _insert_voice(conn, profile_id, 2, is_current=True)
    rows = conn.execute(
        "SELECT version, is_current FROM voice_profiles WHERE profile_id = ? ORDER BY version",
        (profile_id,),
    ).fetchall()
    assert rows == [(1, 0), (2, 1)]
    conn.rollback()


def test_only_one_current_row_per_profile(migrated_db: Path) -> None:
    conn = _connect(migrated_db)
    profile_id = _insert_profile(conn, "one_current")
    _insert_voice(conn, profile_id, 1, is_current=True)
    with pytest.raises(sqlite3.IntegrityError):
        _insert_voice(conn, profile_id, 2, is_current=True)
    conn.rollback()
