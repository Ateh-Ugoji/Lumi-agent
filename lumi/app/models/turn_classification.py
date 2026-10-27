from datetime import UTC, datetime
from typing import Any

from sqlmodel import JSON, Column, Field, SQLModel


class TurnClassification(SQLModel, table=True):
    """One row per classified agent turn (L13 item 9 / PROMPT 5 item 1c).

    Written as a held fire-and-forget task AFTER the reply is sent — a failed
    write never affects the turn. `credits_spent` has no meter yet: NULL, never
    0 (missing metrics are NULL, never 0). `user_corrected` stays NULL until a
    later user message reveals a misroute (a correction / re-ask), so misroutes
    stay findable.
    """

    __tablename__ = "turn_classifications"

    id: int | None = Field(default=None, primary_key=True)
    profile_id: int = Field(foreign_key="profiles.id", index=True)
    message_id: int | None = Field(default=None, foreign_key="chat_messages.id")
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC), index=True
    )

    message_text_hash: str = ""
    message_preview: str = ""  # first ~120 chars

    rule_class: str = "other"
    rule_matched: str | None = None

    jev_called: bool = False
    jev_class: str | None = None
    jev_probs: list[dict[str, Any]] | None = Field(
        default=None, sa_column=Column(JSON)
    )
    jev_confidence: float | None = None
    jev_latency_ms: int | None = None
    jev_error: str | None = None

    final_class: str = "other"
    path_taken: str = "full"  # fast | full
    tools_called: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    credits_spent: float | None = None  # no credit meter: NULL, never 0
    total_latency_ms: int | None = None
    user_corrected: bool | None = None

    # Per-turn latency metrics (PROMPT 5 item 8): prompt_ms, mcp_ms,
    # completion_ms, model, prompt_tokens, completion_tokens, reasoning_tokens…
    # each absent/unknown key stays NULL rather than 0.
    timings: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
