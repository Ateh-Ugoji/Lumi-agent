from datetime import datetime

from sqlmodel import Field, SQLModel


class PollConfig(SQLModel, table=True):
    __tablename__ = "poll_config"

    id: int | None = Field(default=None, primary_key=True)
    profile_id: int = Field(foreign_key="profiles.id", index=True, unique=True)
    interval_minutes: int = 5
    is_active: bool = False
    last_polled_at: datetime | None = None
