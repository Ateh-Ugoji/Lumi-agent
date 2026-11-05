"""Long-term agent memory: durable notes in Postgres, found again through vectors.

Replaces ``memory.md`` and the text-bearing ``agent_memory`` Chroma collection. A note is saved
in Postgres first; the vector is a derived index. If indexing fails the note is still kept and
the result says so (``indexed: false``), and ``reindex_vectors`` repairs it later.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Literal

from lumi_ai.config import AIConfig
from lumi_ai.ports import Clock, MemoryStore
from lumi_ai.rag.collections import AGENT_MEMORY
from lumi_ai.rag.errors import VectorStoreError
from lumi_ai.rag.indexer import VectorIndexer
from lumi_ai.rag.retrieval import Retriever

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RememberResult:
    status: Literal["stored", "duplicate", "empty", "too_long"]
    note_id: int | None = None
    indexed: bool = False
    warning: str = ""


class MemoryService:
    def __init__(
        self,
        store: MemoryStore,
        indexer: VectorIndexer,
        retriever: Retriever,
        clock: Clock,
        config: AIConfig,
    ):
        self._store = store
        self._indexer = indexer
        self._retriever = retriever
        self._clock = clock
        self._cfg = config

    async def remember(
        self, profile_id: int, text: str, kind: str = "fact"
    ) -> RememberResult:
        clean = " ".join(text.split())
        if not clean:
            return RememberResult("empty")
        if len(clean) > self._cfg.memory_note_max_chars:
            return RememberResult(
                "too_long",
                warning=f"keep a note under {self._cfg.memory_note_max_chars} characters",
            )
        note, created = await self._store.add_note(profile_id, clean, kind)
        # A duplicate is re-indexed too: upsert is idempotent and it heals an earlier failure.
        try:
            await asyncio.to_thread(self._indexer.index_notes, [note])
            indexed, warning = True, ""
        except (VectorStoreError, ValueError) as exc:
            logger.warning("memory note %s saved but not indexed: %s", note.id, exc)
            indexed, warning = False, f"saved, but not searchable yet: {exc}"
        return RememberResult(
            "stored" if created else "duplicate", note.id, indexed, warning
        )

    async def recall(self, profile_id: int, query: str, n: int = 5) -> dict[str, Any]:
        """Memories closest to ``query``. Failures are reported, never papered over."""
        try:
            found = await self._retriever.similar_notes(profile_id, query, n)
        except VectorStoreError as exc:
            return {"found": False, "memories": [], "error": str(exc)}
        found = [r for r in found if r.distance <= self._cfg.memory_max_distance]
        if not found:
            has_any = await self._store.list_notes(profile_id, limit=1)
            return {
                "found": False,
                "memories": [],
                "reason": "no_matches" if has_any else "no_memories",
            }
        await self._store.touch_notes([r.item.id for r in found])
        return {
            "found": True,
            "query": query,
            "memories": [
                {
                    "id": r.item.id,
                    "text": r.item.text,
                    "kind": r.item.kind,
                    "distance": round(r.distance, 3),
                }
                for r in found
            ],
        }

    async def decay(self, profile_id: int, older_than_days: int | None = None) -> int:
        """Drop notes unused for ``memory_decay_days``; remove their vectors too."""
        days = older_than_days or self._cfg.memory_decay_days
        cutoff = self._clock.now() - timedelta(days=days)
        ids = await self._store.delete_notes_older_than(profile_id, cutoff)
        if ids:
            await asyncio.to_thread(self._indexer.remove, AGENT_MEMORY, "memory", ids)
        return len(ids)
