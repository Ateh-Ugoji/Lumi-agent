"""add user_search_requests table

Pasted/mentioned handles the user explicitly asked Lumi to look up. Kept
separate from the profile's peer set (peer_frameworks / listening_matches) so a
user-requested recon never pollutes "my peers". Append-only.

Revision ID: d3c4b5a6978e
Revises: b7d2e5f8a3c1
Create Date: 2026-10-20 22:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = 'd3c4b5a6978e'
down_revision: Union[str, Sequence[str], None] = 'b7d2e5f8a3c1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('user_search_requests',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('profile_id', sa.Integer(), nullable=False),
    sa.Column('handle', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('request_note', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('created_at', sqlmodel.sql.sqltypes.UTCDateTime(), nullable=False),
    sa.ForeignKeyConstraint(['profile_id'], ['profiles.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_user_search_requests_profile_id'), 'user_search_requests', ['profile_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_user_search_requests_profile_id'), table_name='user_search_requests')
    op.drop_table('user_search_requests')
