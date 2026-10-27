"""add listening_matches.author_avatar_url (ChronicOnline picture sync)

ChronicOnline showed account pictures straight from unavatar with nothing
persisted, so the feed and the handle DB could disagree. The scan now reads
the picture back from the shared handle DB (Chroma `handle_mappings`) right
after saving matches and stores it on the row; the API serves it and the UI
prefers it, falling back to unavatar only when the store didn't know.

Revision ID: b7f3a91c5d20
Revises: cefd455456a2
Create Date: 2026-10-27 07:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7f3a91c5d20'
down_revision: Union[str, Sequence[str], None] = 'cefd455456a2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add the nullable picture column (existing rows keep NULL until the
    next scan backfills the authors it already knows)."""
    op.add_column("listening_matches", sa.Column("author_avatar_url", sa.String(), nullable=True))


def downgrade() -> None:
    """Drop the column — pictures stay recoverable from the handle DB."""
    op.drop_column("listening_matches", "author_avatar_url")
