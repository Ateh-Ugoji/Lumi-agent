from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, Column, UniqueConstraint
from sqlmodel import Field, SQLModel


class NicheFrameworkReportRow(SQLModel, table=True):
    """One generated peer-framework report.

    The whole `NicheFrameworkReport` JSON contract (schemas/peer.py) lives in
    `payload`, the same pattern as `peer_frameworks.payload`, so the schema can
    evolve without a column per field. `status` is mirrored out for querying
    (`ok` / `insufficient_data` / `failed`).
    """

    __tablename__ = "niche_framework_reports"

    id: int | None = Field(default=None, primary_key=True)
    profile_id: int = Field(foreign_key="profiles.id", index=True)
    niche: str = ""
    status: str = "pending"
    payload: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    posts_analyzed: int = 0
    winner_count: int = 0
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class PostTaggingRow(SQLModel, table=True):
    """One scanned post's blind-tagging record.

    Keyed by `(post_id, prompt_version)` so re-running a pipeline with the same
    prompt reuses prior LLM work and a prompt bump re-tags everything
    (Prompt 1's cache rule). `analysis` stays NULL when the tagging failed —
    a failed row never carries an invented analysis.
    """

    __tablename__ = "post_taggings"
    __table_args__ = (
        UniqueConstraint(
            "post_id", "prompt_version", name="uq_post_taggings_post_id_prompt_version"
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    post_id: str = Field(index=True)
    handle: str = ""
    status: str = "pending"  # pending | ok | failed
    analysis: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    framework_guess: str | None = None
    validation_error: str | None = None
    prompt_version: str = ""
    tagged_at: datetime | None = None
