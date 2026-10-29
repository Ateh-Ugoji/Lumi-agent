"""Agent tool over memory: ``recall_memory``.

There is no ``remember`` tool on purpose: a write tool costs a second model call (the loop must answer
after the tool result) and the extractor already saves durable facts after the reply, so the
model only reads memory.
"""

from __future__ import annotations

from typing import Any

from lumi_ai.rag.memory import MemoryService
from lumi_ai.tools.registry import ToolContext, ToolSpec


def build(service: MemoryService) -> list[ToolSpec]:
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
