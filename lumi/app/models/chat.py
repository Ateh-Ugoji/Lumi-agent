from datetime import UTC, datetime
from enum import Enum
from typing import Any

from sqlmodel import JSON, Column, Field, SQLModel


class ChatRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class ChatMessage(SQLModel, table=True):
    __tablename__ = "chat_messages"

    id: int | None = Field(default=None, primary_key=True)
    profile_id: int = Field(foreign_key="profiles.id", index=True)
    role: ChatRole
    content: str
    tool_calls: list[dict[str, Any]] | None = Field(default=None, sa_column=Column(JSON))
    tool_name: str | None = None
    # One-line summary of the tools this assistant turn ran (item 5): injected
    # back into history as a short note so the model can answer "what tools did
    # you use?" without re-running anything. Null on USER/TOOL rows.
    tools_used: list[str] | None = Field(default=None, sa_column=Column(JSON))
    # The required `reason` argument the model gave for a tool call (item 4):
    # stripped/validated by the registry, stored on the TOOL row, streamed in
    # the SSE tool_start event.
    reason: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
