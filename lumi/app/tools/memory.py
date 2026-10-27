"""Agent memory tools: remember durable facts, recall them on out-of-context references."""

from app.services.memory import append_profile_bullet, recall, remember
from app.tools.registry import tool


@tool(
    name="remember",
    description=(
        "Persist a durable fact, preference, or decision about the user or their project so it "
        "survives across sessions. Use when the user states something worth remembering "
        "(preferences, goals, project details, decisions). Also appends to the rolling memory.md summary."
    ),
    parameters={
        "type": "object",
        "properties": {
            "profile_id": {"type": "integer"},
            "memory": {"type": "string", "description": "The durable fact to remember, as one concise sentence"},
            "kind": {
                "type": "string",
                "description": "Category: fact | preference | decision | context (default: fact)",
            },
        },
        "required": ["profile_id", "memory"],
    },
    side_effects="writes_index",
)
async def remember_tool(profile_id: int, memory: str, kind: str = "fact") -> dict:
    res = remember(profile_id, memory, kind=kind)
    appended = append_profile_bullet(profile_id, memory)
    return {
        "profile_id": profile_id,
        "stored": bool(res.get("stored")),
        "id": res.get("id"),
        "reason": res.get("reason"),
        "summary_appended": appended,
    }


@tool(
    name="recall_memory",
    description=(
        "Semantic search over this profile's long-term memory (facts, preferences, past decisions). "
        "Use when the user references something specific you don't know in depth from the current "
        "context (a past decision, a project detail, something they told you before), or before "
        "answering anything about the user's history or preferences."
    ),
    parameters={
        "type": "object",
        "properties": {
            "profile_id": {"type": "integer"},
            "query": {"type": "string", "description": "What to search for (e.g. 'posting schedule preference')"},
            "limit": {"type": "integer", "description": "Max memories to return (default 5)"},
        },
        "required": ["profile_id", "query"],
    },
    side_effects="none",
)
async def recall_memory_tool(profile_id: int, query: str, limit: int = 5) -> dict:
    out = recall(profile_id, query, n=limit)
    out.setdefault("profile_id", profile_id)
    return out
