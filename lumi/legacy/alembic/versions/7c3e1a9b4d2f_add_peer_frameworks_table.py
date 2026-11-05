"""add peer_frameworks table

Revision ID: 7c3e1a9b4d2f
Revises: 46283ff46bfd
Create Date: 2026-10-12 20:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = '7c3e1a9b4d2f'
down_revision: Union[str, Sequence[str], None] = '46283ff46bfd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('peer_frameworks',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('profile_id', sa.Integer(), nullable=False),
    sa.Column('query', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('niche_title', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('payload', sa.JSON(), nullable=True),
    sa.Column('analyzed_peers_count', sa.Integer(), nullable=False),
    sa.Column('created_at', sqlmodel.sql.sqltypes.UTCDateTime(), nullable=False),
    sa.ForeignKeyConstraint(['profile_id'], ['profiles.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_peer_frameworks_profile_id'), 'peer_frameworks', ['profile_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_peer_frameworks_profile_id'), table_name='peer_frameworks')
    op.drop_table('peer_frameworks')
