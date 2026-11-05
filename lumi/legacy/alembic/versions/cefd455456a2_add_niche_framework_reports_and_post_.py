"""add niche_framework_reports and post_taggings

Prompt 2 of the peer-framework pipeline: persistence for the report (one JSON
`NicheFrameworkReport` per row, same pattern as `peer_frameworks.payload`) and
for per-post blind taggings, unique on (post_id, prompt_version) so a prompt bump
re-tags and a rerun reuses prior LLM work.

Revision ID: cefd455456a2
Revises: 2f30380b96df
Create Date: 2026-10-26 04:11:35.266886

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = 'cefd455456a2'
down_revision: Union[str, Sequence[str], None] = '2f30380b96df'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create the report + tagging tables."""
    op.create_table(
        "niche_framework_reports",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("profile_id", sa.Integer(), nullable=False),
        sa.Column("niche", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("status", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("posts_analyzed", sa.Integer(), nullable=False),
        sa.Column("winner_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sqlmodel.sql.sqltypes.UTCDateTime(), nullable=False),
        sa.ForeignKeyConstraint(["profile_id"], ["profiles.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_niche_framework_reports_profile_id"),
        "niche_framework_reports",
        ["profile_id"],
        unique=False,
    )

    op.create_table(
        "post_taggings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("post_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("handle", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("status", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("analysis", sa.JSON(), nullable=True),
        sa.Column("framework_guess", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("validation_error", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("prompt_version", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("tagged_at", sqlmodel.sql.sqltypes.UTCDateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "post_id", "prompt_version", name="uq_post_taggings_post_id_prompt_version"
        ),
    )
    op.create_index(op.f("ix_post_taggings_post_id"), "post_taggings", ["post_id"], unique=False)


def downgrade() -> None:
    """Drop both tables (report + taggings are derived, re-generable data)."""
    op.drop_index(op.f("ix_post_taggings_post_id"), table_name="post_taggings")
    op.drop_table("post_taggings")
    op.drop_index(op.f("ix_niche_framework_reports_profile_id"), table_name="niche_framework_reports")
    op.drop_table("niche_framework_reports")
