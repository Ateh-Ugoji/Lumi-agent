"""fix sqlite partial voice index

The initial schema declared `uq_voice_profiles_current_per_profile` with
`postgresql_where` only. That kwarg is dialect-scoped, so SQLite ignored it and
the index degenerated to a plain UNIQUE(profile_id) — one voice-profile row per
profile, forever. Inserting a second version then fails with IntegrityError even
when the flip-before-insert + flush order is correct, which breaks versioned
voice profiles on the local dev DB (Postgres was always fine).

`app/models/voice.py` now also declares `sqlite_where`, so new databases get the
partial index from the first migration onward through metadata; this revision
rebuilds the index on SQLite databases that already carry the degenerate one.
No-op on PostgreSQL, where the index is already correct.

Revision ID: 2f30380b96df
Revises: f3a7c9e2b41d
Create Date: 2026-10-26 01:44:12.561850

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = '2f30380b96df'
down_revision: Union[str, Sequence[str], None] = 'f3a7c9e2b41d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Rebuild the index as a real partial index on SQLite (no-op elsewhere)."""
    if op.get_bind().dialect.name != "sqlite":
        return
    op.drop_index("uq_voice_profiles_current_per_profile", table_name="voice_profiles")
    op.create_index(
        "uq_voice_profiles_current_per_profile",
        "voice_profiles",
        ["profile_id"],
        unique=True,
        sqlite_where=sa.text("is_current = 1"),
    )


def downgrade() -> None:
    """One-way fix: deliberately a no-op.

    The pre-fix state (plain UNIQUE(profile_id)) cannot be recreated on a
    database that already holds several voice-profile versions for one profile —
    verified: it raises IntegrityError on `alembic downgrade -1`. Restoring a
    broken index nobody wants back is not worth a failing downgrade, so this
    direction only moves forward.
    """
    return
