"""Agent tools over memory: ``remember`` and ``recall_memory``."""

from __future__ import annotations

from typing import Any

from lumi_ai.rag.memory import MemoryService
from lumi_ai.tools.registry import ToolContext, ToolSpec


def build(service: MemoryService) -> list[ToolSpec]:
    async def remember(
        ctx: ToolContext, text: str, kind: str = "fact"
    ) -> dict[str, Any]:
        outcome = await service.remember(
            ctx.profile_id, str(text or ""), str(kind or "fact")
        )
        out: dict[str, Any] = {"status": outcome.status}
        if outcome.note_id is not None:
            out["id"] = outcome.note_id
            out["searchable"] = outcome.indexed
        if outcome.warning:
            out["warning"] = outcome.warning
        return out

    async def recall_memory(
        ctx: ToolContext, query: str, limit: int = 5
    ) -> dict[str, Any]:
        try:
            n = max(1, min(int(limit), 10))
        except (TypeError, ValueError):
            n = 5
        return await service.recall(ctx.profile_id, str(query or ""), n)

    profile = {"profile_id": {"type": "integer"}}
    return [
        ToolSpec(
            name="remember",
            description=(
                "Store one durable fact the user told you (a preference, a decision, project "
                "context) so it can be recalled in later sessions. Not for passing remarks."
            ),
            parameters={
                "type": "object",
                "properties": {
                    **profile,
                    "text": {
                        "type": "string",
                        "description": "One standalone sentence, under 500 characters.",
                    },
                    "kind": {
                        "type": "string",
                        "description": "fact, preference or decision.",
                    },
                },
                "required": ["profile_id", "text"],
            },
            handler=remember,
            side_effects="writes_db",
            cache_ttl=0,
        ),
        ToolSpec(
            name="recall_memory",
            description=(
                "Search long-term memory for what the user said before. Use it when they refer "
                "to something earlier or you need detail beyond the memory summary."
            ),
            parameters={
                "type": "object",
                "properties": {
                    **profile,
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "description": "1 to 10, default 5."},
                },
                "required": ["profile_id", "query"],
            },
            handler=recall_memory,
            side_effects="writes_db",  # bumps last_accessed_at so decay spares what is used
            cache_ttl=0,
        ),
    ]
