"""T8 importer for ``chat_messages`` (SCHEMA.md section 10.3)."""

from __future__ import annotations

from apps.chat.models import ChatMessage, ChatRole
from apps.core.legacy_import import ImportContext, Importer, register, to_dt, to_json
from apps.core.legacy_import.engine import sync_sequence
from apps.profiles.legacy_import import profile_targets

BATCH = 2000


def import_chat_messages(ctx: ImportContext) -> None:
    t = ctx.table("chat_messages")
    targets = profile_targets(ctx)
    rows = list(ctx.legacy.rows("chat_messages"))
    t.read = len(rows)
    new: list[ChatMessage] = []
    for row in rows:
        pk = row["id"]
        if ctx.is_done("chat_messages", pk, "chat_messages"):
            t.already += 1
            continue
        target = targets.get(row["profile_id"])
        role = str(row.get("role") or "").lower()
        if target is None or role not in ChatRole.values:
            ctx.skip("chat_messages", pk, "sin perfil importado o rol desconocido")
            continue
        tools_used = to_json(row.get("tools_used"))
        tool_calls = to_json(row.get("tool_calls"))
        extra = {}
        if created := to_dt(row.get("created_at")):
            extra["created_at"] = created
        new.append(
            ChatMessage(
                id=pk,
                profile_id=target[0],
                role=role,
                content=row.get("content") or "",
                tool_calls=tool_calls if isinstance(tool_calls, list) else None,
                tool_name=row.get("tool_name"),
                tools_used=[str(x) for x in tools_used]
                if isinstance(tools_used, list)
                else None,
                reason=row.get("reason"),
                **extra,
            )
        )
    ctx.require_free_ids(ChatMessage, [m.id for m in new])
    for i in range(0, len(new), BATCH):
        ChatMessage.objects.bulk_create(new[i : i + BATCH])
    for message in new:
        ctx.remember("chat_messages", message.id, "chat_messages", message.id)
        t.imported += 1
    sync_sequence(ChatMessage)


register(Importer("chat_messages", ("chat_messages",), 80, import_chat_messages))
