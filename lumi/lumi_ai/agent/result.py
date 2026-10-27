"""Types returned by an agent turn. The Django glue (``apps.intelligence.runtime``) returns these."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass(frozen=True, slots=True)
class ToolExecution:
    """One tool call made during a turn, as the frontend shows it."""

    tool: str
    arguments: Mapping[str, Any]
    reason: str | None = None
    ok: bool = True
    sample_posts: Sequence[Mapping[str, Any]] = ()


@dataclass(frozen=True, slots=True)
class TurnResult:
    """Final outcome of one user message.

    Mirrors the legacy ``AgentResult``/``ChatResponse``: ``content`` plus the tools that ran.
    """

    content: str
    tool_calls_made: tuple[str, ...] = ()
    tool_executions: tuple[ToolExecution, ...] = ()
    path_taken: Literal["fast", "full"] = "full"
    assistant_message_id: int | None = None


SSEEventType = Literal["tool_start", "tool_done", "done", "error"]


@dataclass(frozen=True, slots=True)
class SSEEvent:
    """One server-sent event. ``as_dict`` matches the JSON the frontend already parses.

    * ``tool_start``: ``tool``, ``arguments``, ``reason``
    * ``tool_done``: ``tool``, ``sample_posts``
    * ``done``: ``content``, ``tool_executions``
    * ``error``: ``error``
    """

    type: SSEEventType
    data: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"type": self.type, **self.data}

    def encode(self) -> str:
        """Return the wire format: ``data: <json>`` plus a blank line."""
        return f"data: {json.dumps(self.as_dict(), ensure_ascii=False, default=str)}\n\n"
