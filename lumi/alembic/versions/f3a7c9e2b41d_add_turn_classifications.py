"""add turn_classifications table + chat_messages.tools_used / reason

Turn-classifier log (L13 item 9 / PROMPT 5 item 1c): one row per classified
agent turn, written fire-and-forget AFTER the reply. Plus two chat_messages
columns from PROMPT 5 items 4-5: the validated `reason` a tool was called
with (stored on TOOL rows) and the per-assistant-turn `tools_used` summary
(injected back into history as a short note; TOOL rows stay out of context).

Purely additive — nullable columns and a new table, safe for the pre-deploy
window (old code ignores both).

Revision ID: f3a7c9e2b41d
Revises: e4f1a2b3c5d6
Create Date: 2026-10-25 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = 'f3a7c9e2b41d'
down_revision: Union[str, Sequence[str], None] = 'e4f1a2b3c5d6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'turn_classifications',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('profile_id', sa.Integer(), nullable=False),
        sa.Column('message_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sqlmodel.sql.sqltypes.UTCDateTime(), nullable=False),
        sa.Column('message_text_hash', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('message_preview', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('rule_class', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('rule_matched', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('jev_called', sa.Boolean(), nullable=False),
        sa.Column('jev_class', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('jev_probs', sa.JSON(), nullable=True),
        sa.Column('jev_confidence', sa.Float(), nullable=True),
        sa.Column('jev_latency_ms', sa.Integer(), nullable=True),
        sa.Column('jev_error', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('final_class', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('path_taken', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('tools_called', sa.JSON(), nullable=True),
        sa.Column('credits_spent', sa.Float(), nullable=True),
        sa.Column('total_latency_ms', sa.Integer(), nullable=True),
        sa.Column('user_corrected', sa.Boolean(), nullable=True),
        sa.Column('timings', sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(['profile_id'], ['profiles.id']),
        sa.ForeignKeyConstraint(['message_id'], ['chat_messages.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_turn_classifications_profile_id'),
        'turn_classifications',
        ['profile_id'],
        unique=False,
    )
    op.create_index(
        op.f('ix_turn_classifications_created_at'),
        'turn_classifications',
        ['created_at'],
        unique=False,
    )
    op.add_column('chat_messages', sa.Column('tools_used', sa.JSON(), nullable=True))
    op.add_column(
        'chat_messages',
        sa.Column('reason', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('chat_messages', 'reason')
    op.drop_column('chat_messages', 'tools_used')
    op.drop_index(
        op.f('ix_turn_classifications_created_at'), table_name='turn_classifications'
    )
    op.drop_index(
        op.f('ix_turn_classifications_profile_id'), table_name='turn_classifications'
    )
    op.drop_table('turn_classifications')
