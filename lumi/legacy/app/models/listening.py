from datetime import UTC, datetime
from typing import Any

from sqlalchemy import UniqueConstraint
from sqlmodel import JSON, Column, Field, SQLModel


class ListeningMatch(SQLModel, table=True):
    """A post surfaced by social listening (Xpoz) for a profile's tracked keywords/niche.

    Not authored by the profile — unlike `Post`, which is the profile's own backfilled
    content. `profile_id` here means "whose listening config matched this," not "who
    posted this." Feeds `repurpose_caption` as a `source_text` candidate.
    """

    __tablename__ = "listening_matches"
    __table_args__ = (
        UniqueConstraint("profile_id", "platform_post_id", name="uq_listening_matches_profile_id_platform_post_id"),
    )

    id: int | None = Field(default=None, primary_key=True)
    profile_id: int = Field(foreign_key="profiles.id", index=True)
    platform: str = "x"  # MVP targets X only; column kept for extensibility
    platform_post_id: str
    author_handle: str
    # Picture for the author, read from the shared handle DB (Chroma) right
    # after the scan — ChronicOnline and the thinking cards render this so
    # every surface shows the same face. NULL = store didn't know it.
    author_avatar_url: str | None = None
    caption: str
    platform_url: str
    metrics: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    discovered_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    alerted_at: datetime | None = None
    alert_dismissed: bool = False
