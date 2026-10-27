"""Read-only access to a legacy SQLite file and the parsers its values need."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote


class LegacyDb:
    """The legacy ``lumi.db``, opened with ``mode=ro``: the importer cannot change it."""

    def __init__(self, path: str | Path) -> None:
        resolved = Path(path).expanduser().resolve()
        if not resolved.is_file():
            raise FileNotFoundError(f"No existe el archivo SQLite: {resolved}")
        self.path = resolved
        self._conn = sqlite3.connect(f"file:{quote(str(resolved))}?mode=ro", uri=True)
        self._conn.row_factory = sqlite3.Row
        self._tables = {
            r[0]
            for r in self._conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }

    def close(self) -> None:
        self._conn.close()

    def has_table(self, table: str) -> bool:
        return table in self._tables

    def count(self, table: str) -> int:
        if table not in self._tables:
            return 0
        return self._conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]

    def get(self, table: str, pk: Any) -> dict[str, Any] | None:
        if table not in self._tables:
            return None
        found = self._conn.execute(
            f'SELECT * FROM "{table}" WHERE "id" = ?', (pk,)
        ).fetchone()
        return dict(found) if found else None

    def ids(self, table: str) -> set[str]:
        if table not in self._tables:
            return set()
        cursor = self._conn.execute(f'SELECT "id" FROM "{table}"')
        return {str(r[0]) for r in cursor}

    def rows(self, table: str, order_by: str = "id") -> Iterator[dict[str, Any]]:
        """Yield rows as dicts. A missing table yields nothing (older files lack some)."""
        if table not in self._tables:
            return
        cursor = self._conn.execute(f'SELECT * FROM "{table}" ORDER BY "{order_by}"')
        while batch := cursor.fetchmany(1000):
            for row in batch:
                yield dict(row)


def to_dt(value: Any) -> datetime | None:
    """Parse a SQLite datetime. Naive values are UTC (the legacy code wrote UTC)."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value))
        except ValueError:
            return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed


def to_bool(value: Any) -> bool:
    return bool(value) and str(value).lower() not in {"0", "false"}


def to_json(value: Any) -> Any:
    """Decode a JSON column (SQLite keeps it as text). Undecodable text becomes ``None``."""
    if value is None or not isinstance(value, str | bytes):
        return value
    try:
        return json.loads(value)
    except ValueError:
        return None
