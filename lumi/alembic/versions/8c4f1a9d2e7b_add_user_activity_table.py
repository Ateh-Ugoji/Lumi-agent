"""add user_activity table

Revision ID: 8c4f1a9d2e7b
Revises: 7c3e1a9b4d2f
Create Date: 2026-10-12 22:50:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = '8c4f1a9d2e7b'
down_revision: Union[str, Sequence[str], None] = '7c3e1a9b4d2f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('user_activity',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('profile_id', sa.Integer(), nullable=False),
    sa.Column('platform', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('platform_post_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('kind', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('caption', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('published_at', sqlmodel.sql.sqltypes.UTCDateTime(), nullable=False),
    sa.Column('created_at', sqlmodel.sql.sqltypes.UTCDateTime(), nullable=False),
    sa.ForeignKeyConstraint(['profile_id'], ['profiles.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('profile_id', 'platform_post_id', name='uq_user_activity_profile_id_platform_post_id')
    )
    op.create_index(op.f('ix_user_activity_profile_id'), 'user_activity', ['profile_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_user_activity_profile_id'), table_name='user_activity')
    op.drop_table('user_activity')
