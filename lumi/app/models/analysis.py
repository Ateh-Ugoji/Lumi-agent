from datetime import UTC, datetime

from sqlalchemy import JSON, Column, Index
from sqlmodel import Field, SQLModel


class OwnPostAnalysis(SQLModel, table=True):
    """Blind-tagged analysis of the user's OWN posts.

    Same analysis shape as the peer pipeline (PostAnalysis, Runtime Prompt A)
    — persisted per (post_id, prompt_version) so prompt upgrades re-tag.

    status: "pending" (queued, not yet tagged) | "ok" | "failed".
    A pending/failed row carries analysis=NULL — never a fabricated analysis.
    prompt_version stays NULL until the peer extract's prompt lands (the tagging
    call is stubbed until then: app/analysis/own_tagging.py).
    """

    __tablename__ = "own_post_analysis"
    __table_args__ = (
        Index("ix_own_post_analysis_post_id_prompt_version", "post_id", "prompt_version"),
    )

    id: int | None = Field(default=None, primary_key=True)
    post_id: int = Field(foreign_key="posts.id", index=True)
    prompt_version: str | None = None
    analysis: dict | None = Field(
        default=None,
        sa_column=Column(JSON, nullable=True),  # PostAnalysis JSON; NULL when pending/failed
    )
    status: str = "pending"
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
