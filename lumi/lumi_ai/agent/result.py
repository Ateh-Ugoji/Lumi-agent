"""Types returned by an agent turn. The Django glue (``apps.intelligence.runtime``) returns these."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

#: Tools whose result the frontend draws from structured data, and the fields it may receive.
#: ``None`` means the whole result (``get_analytics``: the UI draws the exact numbers the agent saw).
#: Every other tool ships no result, and an error result ships nothing: its text is internal.
SHIPPED_RESULT_FIELDS: dict[str, tuple[str, ...] | None] = {
    "get_analytics": None,
    "connect_account": ("already_connected", "platform", "connect_url", "handle"),
}


def shipped_result(tool: str, result: Any) -> dict[str, Any] | None:
    """The part of ``result`` that may reach the frontend (see ``SHIPPED_RESULT_FIELDS``)."""
    if tool not in SHIPPED_RESULT_FIELDS or not isinstance(result, Mapping):
        return None
    if result.get("error"):
        return None
    fields = SHIPPED_RESULT_FIELDS[tool]
    if fields is None:
        return dict(result)
    # Scalars only: a nested value could carry anything.
    return {
        k: result[k]
        for k in fields
        if k in result and (result[k] is None or isinstance(result[k], str | bool))
    }


@dataclass(frozen=True, slots=True)
class ToolExecution:
    """One tool call made during a turn, as the frontend shows it."""

    tool: str
    arguments: Mapping[str, Any]
    reason: str | None = None
    ok: bool = True
    sample_posts: Sequence[Mapping[str, Any]] = ()
    #: Already filtered by :func:`shipped_result`; never put a raw tool result here.
    result: Mapping[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        """The shape the frontend already parses (``name``, not ``tool``)."""
        out: dict[str, Any] = {
            "name": self.tool,
            "arguments": dict(self.arguments),
            "sample_posts": list(self.sample_posts),
        }
        if self.result is not None:
            out["result"] = dict(self.result)
        return out


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
        return (
            f"data: {json.dumps(self.as_dict(), ensure_ascii=False, default=str)}\n\n"
        )
