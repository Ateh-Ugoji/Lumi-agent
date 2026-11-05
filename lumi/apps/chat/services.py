"""Chat history of one profile. Implements ``lumi_ai.ports.ChatStore`` (sync and async)."""

from __future__ import annotations

from collections.abc import Sequence

from asgiref.sync import sync_to_async

from apps.chat.models import ChatMessage
from lumi_ai.ports import ChatMessageIn, ChatMessageOut

__all__ = [
    "HISTORY_ROLES",
    "aappend",
    "aappend_message",
    "aclear_history",
    "ahistory",
    "ahistory_page",
    "append",
    "append_message",
    "clear_history",
    "history",
    "history_page",
]

HISTORY_ROLES = ("user", "assistant")  # what the UI shows; "tool" rows are internal
MAX_LIMIT = 200


def append_message(profile_id: int, message: ChatMessageIn) -> int:
    """Store a message and return its id."""
    row = ChatMessage.objects.create(
        profile_id=profile_id,
        role=message.role,
        content=message.content,
        tool_calls=list(message.tool_calls) if message.tool_calls is not None else None,
        tool_name=message.tool_name,
        tools_used=list(message.tools_used) if message.tools_used is not None else None,
        reason=message.reason,
        tool_call_id=message.tool_call_id,
    )
    return row.pk


def _out(row: ChatMessage) -> ChatMessageOut:
    return ChatMessageOut(
        id=row.pk,
        profile_id=row.profile_id,
        role=row.role,  # type: ignore[arg-type]
        content=row.content,
        created_at=row.created_at,
        tool_calls=tuple(row.tool_calls) if row.tool_calls is not None else None,
        tool_name=row.tool_name,
        tools_used=tuple(row.tools_used) if row.tools_used is not None else None,
        reason=row.reason,
        tool_call_id=row.tool_call_id,
    )


def history(profile_id: int, limit: int = 50) -> list[ChatMessageOut]:
    """The last ``limit`` messages, oldest first, every role (what the model needs)."""
    return _page(profile_id, limit=limit, before=None, roles=None)


def history_page(
    profile_id: int, limit: int = 50, before: int | None = None
) -> list[ChatMessageOut]:
    """User and assistant messages for the UI, oldest first; ``before`` is a message id."""
    return _page(profile_id, limit=limit, before=before, roles=HISTORY_ROLES)


def _page(
    profile_id: int, *, limit: int, before: int | None, roles: Sequence[str] | None
) -> list[ChatMessageOut]:
    limit = max(1, min(int(limit), MAX_LIMIT))
    rows = ChatMessage.objects.filter(profile_id=profile_id)
    if roles is not None:
        rows = rows.filter(role__in=roles)
    if before is not None:
        rows = rows.filter(pk__lt=before)
    newest_first = list(rows.order_by("-id")[:limit])
    return [_out(row) for row in reversed(newest_first)]


def clear_history(profile_id: int) -> int:
    """Delete the whole conversation. Returns the number of rows removed."""
    deleted, _ = ChatMessage.objects.filter(profile_id=profile_id).delete()
    return deleted


# ``ChatStore.append`` is the port name; ``append_message`` is the CONTRATOS name.
append = append_message
aappend_message = sync_to_async(append_message, thread_sensitive=True)
aappend = aappend_message
ahistory = sync_to_async(history, thread_sensitive=True)
ahistory_page = sync_to_async(history_page, thread_sensitive=True)
aclear_history = sync_to_async(clear_history, thread_sensitive=True)
