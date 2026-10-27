"""profile extract fixes: nullable metrics, snapshot age, provenance, own-analysis tables

Revision ID: b7d2e5f8a3c1
Revises: 8c4f1a9d2e7b
Create Date: 2026-10-17 04:30:00.000000

Additive-only schema change from profile_extract_fixes.md (Step 0 numbers in
docs/profile_extract_audit.md):

- metric_snapshots: likes/comments/shares/views become NULLable (missing metric
  must be NULL, never 0) + age_hours + source.
- Data fix Rule A (brief): views==0 with any other metric > 0 -> all NULL (0 rows today).
- Data fix Rule B (audit-driven): all four metrics == 0 AND the snapshot was taken
  >72h after publish -> all NULL (24 rows today: a payload loss, not performance).
  All other zeros are left alone — a young post genuinely at zero stays 0.
- posts: source, last_seen_at, is_deleted_suspect, text_truncated, kind,
  kind_source, conversation_id, thread_position, is_thread_head.
  (kind/kind_source/conversation_id are niche Prompt 1's planned columns merged
  here because Step 2 needs them now — niche Prompt 1 must NOT re-add them.)
- profiles: timezone, timezone_source.
- user_activity: likes, replies, views, source.
- New tables: profile_snapshots, profile_baseline, own_post_analysis.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = 'b7d2e5f8a3c1'
down_revision: Union[str, Sequence[str], None] = '8c4f1a9d2e7b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _snapshot_age_over_72h_clause() -> str:
    """Dialect-specific "snapshot taken > 72h after publish" EXISTS clause."""
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        return (
            "EXISTS (SELECT 1 FROM posts WHERE posts.id = metric_snapshots.post_id "
            "AND EXTRACT(EPOCH FROM (metric_snapshots.captured_at - posts.published_at)) / 3600.0 > 72)"
        )
    # sqlite: julianday diff in days -> hours
    return (
        "EXISTS (SELECT 1 FROM posts WHERE posts.id = metric_snapshots.post_id "
        "AND (julianday(metric_snapshots.captured_at) - julianday(posts.published_at)) * 24 > 72)"
    )


def upgrade() -> None:
    """Upgrade schema."""
    # --- metric_snapshots: drop NOT NULL (SQLite cannot ALTER COLUMN -> batch rebuild) ---
    with op.batch_alter_table('metric_snapshots') as batch_op:
        batch_op.alter_column('likes', existing_type=sa.Integer(), nullable=True)
        batch_op.alter_column('comments', existing_type=sa.Integer(), nullable=True)
        batch_op.alter_column('shares', existing_type=sa.Integer(), nullable=True)
        batch_op.alter_column('views', existing_type=sa.Integer(), nullable=True)
        batch_op.add_column(sa.Column('age_hours', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('source', sqlmodel.sql.sqltypes.AutoString(), nullable=True))

    # --- data fix Rule A (brief): missing views with real other metrics -> NULL ---
    op.execute(sa.text(
        "UPDATE metric_snapshots SET views = NULL, likes = NULL, comments = NULL, shares = NULL "
        "WHERE views = 0 AND (COALESCE(likes, 0) > 0 OR COALESCE(comments, 0) > 0 OR COALESCE(shares, 0) > 0)"
    ))
    # --- data fix Rule B (audit-driven): all-four-zero taken >72h after publish -> NULL.
    # All other zeros are left alone on purpose: a young post genuinely at zero is real. ---
    op.execute(sa.text(
        "UPDATE metric_snapshots SET views = NULL, likes = NULL, comments = NULL, shares = NULL "
        f"WHERE views = 0 AND likes = 0 AND comments = 0 AND shares = 0 "
        f"AND {_snapshot_age_over_72h_clause()}"
    ))

    # --- posts ---
    op.add_column('posts', sa.Column('source', sqlmodel.sql.sqltypes.AutoString(), nullable=True))
    op.add_column('posts', sa.Column('last_seen_at', sqlmodel.sql.sqltypes.UTCDateTime(), nullable=True))
    # server_default needed because ADD COLUMN NOT NULL on a populated SQLite table
    # requires a default; the model keeps its app-side default=False.
    op.add_column('posts', sa.Column('is_deleted_suspect', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('posts', sa.Column('text_truncated', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('posts', sa.Column('kind', sqlmodel.sql.sqltypes.AutoString(), nullable=True))
    op.add_column('posts', sa.Column('kind_source', sqlmodel.sql.sqltypes.AutoString(), nullable=True))
    op.add_column('posts', sa.Column('conversation_id', sqlmodel.sql.sqltypes.AutoString(), nullable=True))
    op.add_column('posts', sa.Column('thread_position', sa.Integer(), nullable=True))
    op.add_column('posts', sa.Column('is_thread_head', sa.Boolean(), nullable=True))

    # --- profiles ---
    op.add_column('profiles', sa.Column('timezone', sqlmodel.sql.sqltypes.AutoString(), nullable=True))
    op.add_column('profiles', sa.Column('timezone_source', sqlmodel.sql.sqltypes.AutoString(), nullable=True))

    # --- user_activity ---
    op.add_column('user_activity', sa.Column('likes', sa.Integer(), nullable=True))
    op.add_column('user_activity', sa.Column('replies', sa.Integer(), nullable=True))
    op.add_column('user_activity', sa.Column('views', sa.Integer(), nullable=True))
    op.add_column('user_activity', sa.Column('source', sqlmodel.sql.sqltypes.AutoString(), nullable=True))

    # --- profile_snapshots: one row per ingestion pass ---
    op.create_table(
        'profile_snapshots',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('profile_id', sa.Integer(), nullable=False),
        sa.Column('captured_at', sqlmodel.sql.sqltypes.UTCDateTime(), nullable=False),
        sa.Column('followers', sa.Integer(), nullable=True),
        sa.Column('following', sa.Integer(), nullable=True),
        sa.Column('source', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.ForeignKeyConstraint(['profile_id'], ['profiles.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_profile_snapshots_profile_id'), 'profile_snapshots', ['profile_id'], unique=False)

    # --- profile_baseline: own-account median/p75 over recent originals ---
    op.create_table(
        'profile_baseline',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('profile_id', sa.Integer(), nullable=False),
        sa.Column('window_days', sa.Integer(), nullable=False),
        sa.Column('n_posts', sa.Integer(), nullable=False),
        sa.Column('median_views', sa.Float(), nullable=False),
        sa.Column('median_engagement', sa.Float(), nullable=False),
        sa.Column('p75_views', sa.Float(), nullable=False),
        sa.Column('baseline_reliable', sa.Boolean(), nullable=False),
        sa.Column('computed_at', sqlmodel.sql.sqltypes.UTCDateTime(), nullable=False),
        sa.ForeignKeyConstraint(['profile_id'], ['profiles.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_profile_baseline_profile_id'), 'profile_baseline', ['profile_id'], unique=False)

    # --- own_post_analysis: blind tagging of own posts (Runtime Prompt A cache) ---
    op.create_table(
        'own_post_analysis',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('post_id', sa.Integer(), nullable=False),
        sa.Column('prompt_version', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('analysis', sa.JSON(), nullable=True),
        sa.Column('status', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('created_at', sqlmodel.sql.sqltypes.UTCDateTime(), nullable=False),
        sa.ForeignKeyConstraint(['post_id'], ['posts.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_own_post_analysis_post_id_prompt_version', 'own_post_analysis', ['post_id', 'prompt_version'], unique=False)
    op.create_index(op.f('ix_own_post_analysis_post_id'), 'own_post_analysis', ['post_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_own_post_analysis_post_id'), table_name='own_post_analysis')
    op.drop_index('ix_own_post_analysis_post_id_prompt_version', table_name='own_post_analysis')
    op.drop_table('own_post_analysis')
    op.drop_index(op.f('ix_profile_baseline_profile_id'), table_name='profile_baseline')
    op.drop_table('profile_baseline')
    op.drop_index(op.f('ix_profile_snapshots_profile_id'), table_name='profile_snapshots')
    op.drop_table('profile_snapshots')

    op.drop_column('user_activity', 'source')
    op.drop_column('user_activity', 'views')
    op.drop_column('user_activity', 'replies')
    op.drop_column('user_activity', 'likes')

    op.drop_column('profiles', 'timezone_source')
    op.drop_column('profiles', 'timezone')

    op.drop_column('posts', 'is_thread_head')
    op.drop_column('posts', 'thread_position')
    op.drop_column('posts', 'conversation_id')
    op.drop_column('posts', 'kind_source')
    op.drop_column('posts', 'kind')
    op.drop_column('posts', 'text_truncated')
    op.drop_column('posts', 'is_deleted_suspect')
    op.drop_column('posts', 'last_seen_at')
    op.drop_column('posts', 'source')

    # metric_snapshots back to NOT NULL: NULLs must be filled (rollback coerces
    # missing -> 0 again; information loss is one-way, documented in the upgrade).
    op.execute(sa.text(
        "UPDATE metric_snapshots SET likes = COALESCE(likes, 0), comments = COALESCE(comments, 0), "
        "shares = COALESCE(shares, 0), views = COALESCE(views, 0)"
    ))
    with op.batch_alter_table('metric_snapshots') as batch_op:
        batch_op.drop_column('source')
        batch_op.drop_column('age_hours')
        batch_op.alter_column('views', existing_type=sa.Integer(), nullable=False)
        batch_op.alter_column('shares', existing_type=sa.Integer(), nullable=False)
        batch_op.alter_column('comments', existing_type=sa.Integer(), nullable=False)
        batch_op.alter_column('likes', existing_type=sa.Integer(), nullable=False)
