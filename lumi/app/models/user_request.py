from datetime import UTC, datetime

from sqlmodel import Field, SQLModel


class UserSearchRequest(SQLModel, table=True):
    """A handle the USER explicitly asked Lumi to look up.

    Deliberately separate from the profile's peer set (`peer_frameworks` /
    `listening_matches`): pasting a username records a request here and never
    merges it into the profile's peer data. Append-only log — re-requests add
    rows; `already_requested` is computed at read time.
    """

    __tablename__ = "user_search_requests"

    id: int | None = Field(default=None, primary_key=True)
    profile_id: int = Field(foreign_key="profiles.id", index=True)
    handle: str  # normalized: no leading @, lowercase
    request_note: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
