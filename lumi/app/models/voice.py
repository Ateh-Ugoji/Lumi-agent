from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Index, UniqueConstraint, text
from sqlmodel import JSON, Column, Field, SQLModel


class VoiceProfile(SQLModel, table=True):
    __tablename__ = "voice_profiles"
    __table_args__ = (
        UniqueConstraint("profile_id", "version", name="uq_voice_profiles_profile_id_version"),
        Index(
            "uq_voice_profiles_current_per_profile",
            "profile_id",
            unique=True,
            postgresql_where=text("is_current = true"),
            # SQLite ignores postgresql_where and would degrade the index to a plain
            # UNIQUE(profile_id), breaking voice-profile versioning locally.
            sqlite_where=text("is_current = 1"),
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    profile_id: int = Field(foreign_key="profiles.id", index=True)
    version: int
    is_current: bool = False
    # tone, emoji use, hook style, vocabulary, structure, things they never do
    payload: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    example_post_ids: list[int] = Field(default_factory=list, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class StyleAnswer(SQLModel, table=True):
    __tablename__ = "style_answers"

    id: int | None = Field(default=None, primary_key=True)
    profile_id: int = Field(foreign_key="profiles.id", index=True)
    question_key: str
    answer: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
