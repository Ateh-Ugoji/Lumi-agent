"""add mcp_auth_accounts table

Stores OAuth tokens for MCP connector auth accounts (one row per account, e.g.
"google"; the Drive and Docs MCP servers share a single union-scope token).
Purely additive — safe for the pre-deploy window (old code ignores it).

Revision ID: e4f1a2b3c5d6
Revises: d3c4b5a6978e
Create Date: 2026-10-21 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = 'e4f1a2b3c5d6'
down_revision: Union[str, Sequence[str], None] = 'd3c4b5a6978e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('mcp_auth_accounts',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('account', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('access_token', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('refresh_token', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('token_type', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('scopes', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('expires_at', sqlmodel.sql.sqltypes.UTCDateTime(), nullable=True),
    sa.Column('updated_at', sqlmodel.sql.sqltypes.UTCDateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_mcp_auth_accounts_account'), 'mcp_auth_accounts', ['account'], unique=True)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_mcp_auth_accounts_account'), table_name='mcp_auth_accounts')
    op.drop_table('mcp_auth_accounts')
