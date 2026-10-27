from datetime import UTC, datetime

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel


class UserActivity(SQLModel, table=True):
    """The user's non-original posts: replies and retweets.

    Deliberately separate from `posts` (authentic originals used for voice
    extraction, captions, analytics). Replies are the user's own words —
    useful for deeper conversational context ("since you said X…").
    Retweets are content the user shared, never authored, and must never be
    attributed to them.
    """

    __tablename__ = "user_activity"
    __table_args__ = (
        UniqueConstraint("profile_id", "platform_post_id", name="uq_user_activity_profile_id_platform_post_id"),
    )

    id: int | None = Field(default=None, primary_key=True)
    profile_id: int = Field(foreign_key="profiles.id", index=True)
    platform: str = "x"
    platform_post_id: str
    kind: str  # "reply" | "retweet"
    caption: str
    published_at: datetime
    # --- profile-extract fixes (additive) ---
    likes: int | None = None  # reply/RT metrics when the source provides them
    replies: int | None = None
    views: int | None = None
    source: str | None = None  # "pfm" | "xpoz"
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
