from datetime import UTC, datetime
from enum import Enum

from sqlmodel import Field, SQLModel


class UserActionType(str, Enum):
    ACCEPT = "accept"
    EDIT = "edit"
    REJECT = "reject"


class RepurposeRequest(SQLModel, table=True):
    __tablename__ = "repurpose_requests"

    id: int | None = Field(default=None, primary_key=True)
    profile_id: int = Field(foreign_key="profiles.id", index=True)
    source_caption: str
    route_label: str | None = None  # easy, standard, hard
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class RepurposeAttempt(SQLModel, table=True):
    __tablename__ = "repurpose_attempts"

    id: int | None = Field(default=None, primary_key=True)
    request_id: int = Field(foreign_key="repurpose_requests.id", index=True)
    platform: str = "x"  # MVP targets X only
    tier: str | None = None  # small, large
    model: str | None = None  # actual model ID used
    provider: str | None = None  # groq, openrouter
    attempt_no: int = 1
    output: str
    must_keep_passed: bool
    judge_verdict: str | None = None  # yes, no, or null if judge unavailable
    judge_confidence: float | None = None  # Jev's calibrated confidence; null if Llama fallback was used
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class UserAction(SQLModel, table=True):
    __tablename__ = "user_actions"

    id: int | None = Field(default=None, primary_key=True)
    attempt_id: int = Field(foreign_key="repurpose_attempts.id", index=True)
    action: UserActionType
    edited_text: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
