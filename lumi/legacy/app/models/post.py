from datetime import datetime

from sqlalchemy import Index, UniqueConstraint, text
from sqlmodel import Field, SQLModel


class Post(SQLModel, table=True):
    __tablename__ = "posts"
    __table_args__ = (UniqueConstraint("profile_id", "platform_post_id", name="uq_posts_profile_id_platform_post_id"),)

    id: int | None = Field(default=None, primary_key=True)
    profile_id: int = Field(foreign_key="profiles.id", index=True)
    platform_post_id: str
    caption: str
    published_at: datetime
    alerted_at: datetime | None = None
    alert_dismissed: bool = False

    # --- profile-extract fixes (additive; NULL on legacy rows) ---
    source: str | None = None  # which ingestion path wrote this: "pfm" | "xpoz"
    last_seen_at: datetime | None = None  # last pass that actually fetched this post
    is_deleted_suspect: bool = False  # missed by two consecutive complete passes (<30d old)
    text_truncated: bool = False  # suspected cut-off text; excluded from hook/body analysis
    # kind/kind_source/conversation_id merged from niche Prompt 1's planned columns
    # (that prompt must not re-add them); kind NULL on legacy rows = original.
    kind: str | None = None  # "original" | "reply" | "retweet" | "quote"
    kind_source: str | None = None  # "api" | "heuristic" — how classify_post_item decided
    conversation_id: str | None = None
    thread_position: int | None = None  # 1-based within conversation (ingest order)
    is_thread_head: bool | None = None


class MetricSnapshot(SQLModel, table=True):
    __tablename__ = "metric_snapshots"
    __table_args__ = (
        UniqueConstraint("post_id", "captured_at", name="uq_metric_snapshots_post_id_captured_at"),
        Index("ix_metric_snapshots_post_id_captured_at_desc", "post_id", text("captured_at DESC")),
    )

    id: int | None = Field(default=None, primary_key=True)
    post_id: int = Field(foreign_key="posts.id", index=True)
    # likes/comments/shares/views are nullable since the profile-extract fix:
    # a missing metric must be NULL, NEVER 0 (0 drags medians/baselines/outliers).
    # Legacy all-zero rows were migrated — see docs/profile_extract_audit.md.
    age_hours: float | None = None  # captured_at - published_at; NULL on legacy rows
    source: str | None = None  # "pfm" | "xpoz"
    captured_at: datetime
    likes: int | None = None
    comments: int | None = None
    shares: int | None = None
    views: int | None = None
