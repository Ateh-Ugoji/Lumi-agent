"""Agent memory: rolling `memory.md` summary + Chroma `agent_memory` long-term store.

Two layers that work together:
- `memory.md` (project root, gitignored): a human-readable rolling summary per
  profile. Regenerated after each turn by the LLM extractor so it always reflects
  "everything" worth remembering, and it is injected into the system prompt.
- Chroma `agent_memory`: individual durable facts, semantic-searchable on demand
  via the `recall_memory` tool when the user references something that needs depth
  beyond what fits in the prompt.

Every helper degrades gracefully: Chroma down → remember/recall no-op (summary
still works), LLM down → extraction skipped (nothing written).
"""

import json
import logging
import re
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from app.agent.providers import chat_completion_with_fallback
from app.config import get_settings
from app.services.chroma import AGENT_MEMORY, get_collection

log = logging.getLogger(__name__)

MEMORY_PATH = Path(__file__).resolve().parents[2] / "memory.md"
MEMORY_DECAY_DAYS = 90

MEMORY_FILE_HEADER = """\
# Agent Memory

> Rolling per-profile summary maintained by Lumi. Rewritten after each turn by the
> memory extractor; durable facts are also indexed in Chroma `agent_memory` for
> semantic recall (`recall_memory`). Do not edit by hand while the agent is running.

"""


# ─────────────────────────── memory.md (rolling summary) ───────────────────────────


def _section_pattern(profile_id: int) -> re.Pattern[str]:
    return re.compile(rf"(?ms)^## Profile {profile_id}\b[^\n]*\n(.*?)(?=^## |\Z)")


def get_profile_summary(profile_id: int, path: Path | str | None = None) -> str:
    """Return the profile's summary section body (markdown bullets), or ''."""
    p = Path(path) if path else MEMORY_PATH
    try:
        if not p.exists():
            return ""
        m = _section_pattern(profile_id).search(p.read_text(encoding="utf-8"))
        return m.group(1).strip("\n") if m else ""
    except Exception as exc:  # noqa: BLE001
        log.warning("memory.md read failed: %s", exc)
        return ""


def upsert_profile_summary(
    profile_id: int, body: str, handle: str = "", path: Path | str | None = None
) -> str:
    """Replace (or create) the profile's section with a new rolling summary body."""
    p = Path(path) if path else MEMORY_PATH
    try:
        text = p.read_text(encoding="utf-8") if p.exists() else MEMORY_FILE_HEADER

        existing_header = None
        pat = _section_pattern(profile_id)
        header_match = re.search(rf"(?m)^## Profile {profile_id}\b[^\n]*", text)
        if header_match:
            existing_header = header_match.group(0)
        header = existing_header or (
            f"## Profile {profile_id} (@{handle})" if handle else f"## Profile {profile_id}"
        )

        body_clean = body.strip().strip("`").strip()
        if body_clean.startswith("## Profile"):
            # LLM echoed a header — keep only what follows it
            body_clean = body_clean.split("\n", 1)[1].strip() if "\n" in body_clean else ""

        block = f"{header}\n{body_clean}\n\n"
        if pat.search(text):
            text = pat.sub(lambda _m: block, text, count=1)
        else:
            text = text.rstrip() + "\n\n" + block
        p.write_text(text, encoding="utf-8")
        return body_clean
    except Exception as exc:  # noqa: BLE001
        log.warning("memory.md write failed: %s", exc)
        return body


def append_profile_bullet(
    profile_id: int, text: str, handle: str = "", path: Path | str | None = None
) -> bool:
    """Append a durable fact as a bullet in the profile's summary (idempotent)."""
    bullet = text.strip()
    if not bullet:
        return False
    bullet = bullet.removeprefix("- ")
    current = get_profile_summary(profile_id, path)
    if bullet in current:
        return False
    body = (current + "\n" if current else "") + f"- {bullet}"
    upsert_profile_summary(profile_id, body, handle=handle, path=path)
    return True


# ─────────────────────────── Chroma agent_memory (recall) ───────────────────────────


def remember(profile_id: int, text: str, kind: str = "fact") -> dict[str, Any]:
    """Store one durable fact in Chroma. Dedupes exact matches within the profile."""
    memory_text = text.strip()
    if not memory_text:
        return {"stored": False, "reason": "empty"}
    col = get_collection(AGENT_MEMORY)
    if col is None:
        return {"stored": False, "reason": "chroma_unavailable"}

    now = datetime.now(UTC).isoformat()
    try:
        # Chroma Cloud caps per-request Get at limit=300
        existing = col.get(where={"profile_id": profile_id}, limit=300)
        for doc_id, doc in zip(existing.get("ids") or [], existing.get("documents") or [], strict=False):
            if (doc or "").strip() == memory_text:
                return {"stored": False, "reason": "duplicate", "id": doc_id}

        mem_id = f"{profile_id}:{uuid.uuid4().hex[:12]}"
        col.add(
            ids=[mem_id],
            documents=[memory_text],
            metadatas=[
                {
                    "profile_id": profile_id,
                    "kind": kind,
                    "created_at": now,
                    "access_count": 0,
                    "last_accessed": now,
                }
            ],
        )
        return {"stored": True, "id": mem_id}
    except Exception as exc:  # noqa: BLE001
        log.warning("remember failed for profile %s: %s", profile_id, exc)
        return {"stored": False, "reason": str(exc)}


def recall(profile_id: int, query: str, n: int = 5) -> dict[str, Any]:
    """Semantic search over this profile's memories; bumps access metadata on hits."""
    col = get_collection(AGENT_MEMORY)
    if col is None:
        return {"found": False, "memories": [], "reason": "chroma_unavailable"}
    try:
        existing = col.get(where={"profile_id": profile_id}, limit=1)
        if not existing.get("ids"):
            return {"found": False, "memories": [], "reason": "no_memories"}

        res = col.query(query_texts=[query], n_results=n, where={"profile_id": profile_id})
        now = datetime.now(UTC).isoformat()
        memories: list[dict[str, Any]] = []
        update_ids: list[str] = []
        update_metas: list[dict[str, Any]] = []
        for batch in range(len(res.get("ids") or [])):
            for i, mem_id in enumerate(res["ids"][batch]):
                meta = dict((res.get("metadatas") or [[]])[batch][i] or {})
                distance = (res.get("distances") or [[]])[batch][i]
                memories.append(
                    {
                        "id": mem_id,
                        "text": (res.get("documents") or [[]])[batch][i],
                        "kind": meta.get("kind", "fact"),
                        "distance": distance,
                    }
                )
                meta["access_count"] = int(meta.get("access_count") or 0) + 1
                meta["last_accessed"] = now
                update_ids.append(mem_id)
                update_metas.append(meta)
        if update_ids:
            col.update(ids=update_ids, metadatas=update_metas)
        return {"found": bool(memories), "query": query, "memories": memories}
    except Exception as exc:  # noqa: BLE001
        log.warning("recall failed for profile %s: %s", profile_id, exc)
        return {"found": False, "memories": [], "reason": str(exc)}


def decay_memories(older_than_days: int = MEMORY_DECAY_DAYS) -> int:
    """Delete memories not accessed/created since the cutoff. Returns count removed."""
    col = get_collection(AGENT_MEMORY)
    if col is None:
        return 0
    try:
        # Chroma Cloud caps per-request Get at limit=300 — paginate
        ids: list[str] = []
        metas: list[Any] = []
        offset = 0
        while True:
            res = col.get(limit=300, offset=offset)
            batch_ids = res.get("ids") or []
            if not batch_ids:
                break
            ids.extend(batch_ids)
            metas.extend(res.get("metadatas") or [])
            if len(batch_ids) < 300:
                break
            offset += 300
        cutoff = datetime.now(UTC) - timedelta(days=older_than_days)
        stale: list[str] = []
        for mem_id, meta in zip(ids, metas, strict=False):
            ts = (meta or {}).get("last_accessed") or (meta or {}).get("created_at")
            if not ts:
                continue
            try:
                dt = datetime.fromisoformat(str(ts))
            except ValueError:
                continue
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            if dt < cutoff:
                stale.append(mem_id)
        if stale:
            col.delete(ids=stale)
        return len(stale)
    except Exception as exc:  # noqa: BLE001
        log.warning("memory decay failed: %s", exc)
        return 0


# ─────────────────────────── end-of-turn extraction ───────────────────────────

MEMORY_EXTRACT_SYSTEM_PROMPT = """\
You maintain an agent's long-term memory for a social-media creator profile.
You receive the previous rolling summary plus one new conversation turn.

Return ONLY JSON:
{
  "memories": ["short durable fact worth storing individually", ...],
  "summary": "the complete updated rolling summary as markdown bullets, one per line, each starting with '- '"
}

Rules:
- memories: only durable, specific facts (preferences, decisions, project details, recurring context).
  Never include pleasantries, transient requests, or anything already implied by the summary.
- summary: merge the prior summary with anything new. Drop stale/contradicted items.
  Keep it tight (ideally under 15 bullets). This is the ONLY context the agent will
  have next session, so keep anything it would need to know.
- If nothing changed: "memories": [] and return the prior summary unchanged.
"""


def _parse_llm_json(raw: str) -> dict[str, Any]:
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.startswith("json"):
            cleaned = cleaned[4:].strip()
    data = json.loads(cleaned)
    if isinstance(data, list) and data and isinstance(data[0], dict):
        data = data[0]
    if not isinstance(data, dict):
        raise TypeError("expected a JSON object")
    return data


async def extract_turn_memories(
    profile_id: int,
    user_message: str,
    assistant_reply: str,
    handle: str = "",
    path: Path | str | None = None,
) -> dict[str, Any]:
    """Extract durable memories from one turn: update memory.md + store facts in Chroma.

    Fire-and-forget from the agent loop. Never raises.
    """
    settings = get_settings()
    if not settings.groq_api_key and not settings.openrouter_api_key:
        return {"stored": 0, "skipped": "no_llm_keys"}

    prior = get_profile_summary(profile_id, path)
    user_prompt = (
        f"PRIOR SUMMARY:\n{prior or '(empty)'}\n\n"
        f"NEW TURN:\nUser: {user_message}\n\nAssistant: {assistant_reply}"
    )
    messages = [
        {"role": "system", "content": MEMORY_EXTRACT_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]

    try:
        completion = await chat_completion_with_fallback(messages, tools=[])
        data = _parse_llm_json(completion.choices[0].message.content or "{}")
    except Exception as exc:  # noqa: BLE001
        log.warning("memory extraction failed for profile %s: %s", profile_id, exc)
        return {"stored": 0, "error": str(exc)}

    memories = [str(m).strip() for m in (data.get("memories") or []) if str(m).strip()]
    summary = str(data.get("summary") or "").strip()

    stored = 0
    for m in memories:
        if remember(profile_id, m, kind="extracted").get("stored"):
            stored += 1

    summary_updated = False
    if summary and summary != prior:
        upsert_profile_summary(profile_id, summary, handle=handle, path=path)
        summary_updated = True

    return {"stored": stored, "summary_updated": summary_updated}
