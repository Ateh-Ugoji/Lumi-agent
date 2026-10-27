from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel


class PeerFramework(SQLModel, table=True):
    """Extracted niche frameworks saved for a profile after peer-winner analysis."""

    __tablename__ = "peer_frameworks"

    id: int | None = Field(default=None, primary_key=True)
    profile_id: int = Field(foreign_key="profiles.id", index=True)
    query: str = ""
    niche_title: str = ""
    payload: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    analyzed_peers_count: int = 0
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
