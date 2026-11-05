"""Read side: embed the query, ask Chroma for ids, then fetch the real rows from Postgres.

Chroma only knows which ids are close. A vector whose row is gone, or whose row belongs to
another profile, is dropped (and a vector whose row is gone is deleted from the index).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Protocol, TypeVar

from lumi_ai.ports import (
    Embedder,
    MemoryNoteOut,
    MemoryStore,
    PeerPostOut,
    PeerPostStore,
    PostOut,
    PostStore,
    VectorStore,
)
from lumi_ai.rag.collections import (
    AGENT_MEMORY,
    PEER_POSTS,
    VOICE_CORPUS,
    parse_vector_id,
    vector_id,
)
from lumi_ai.style.service import authentic_originals

logger = logging.getLogger(__name__)


class _Row(Protocol):
    @property
    def id(self) -> int: ...
    @property
    def profile_id(self) -> int: ...


R = TypeVar("R", bound=_Row)


@dataclass(frozen=True, slots=True)
class Recalled[T]:
    item: T
    distance: float  # cosine distance: 0 identical, 2 opposite


class Retriever:
    def __init__(
        self,
        embedder: Embedder,
        vectors: VectorStore,
        *,
        posts: PostStore | None = None,
        peers: PeerPostStore | None = None,
        memory: MemoryStore | None = None,
    ):
        self._embedder = embedder
        self._vectors = vectors
        self._posts = posts
        self._peers = peers
        self._memory = memory

    async def similar_posts(
        self, profile_id: int, query: str, k: int = 5, *, platform: str | None = None
    ) -> list[Recalled[PostOut]]:
        """The user's own posts closest to ``query`` (examples of their voice)."""
        if self._posts is None:
            raise RuntimeError("Retriever built without a PostStore")
        found = await self._search(
            VOICE_CORPUS,
            "post",
            profile_id,
            query,
            k,
            {"platform": platform} if platform else {},
            self._posts.get_posts,
        )
        keep = {p.id for p in authentic_originals([r.item for r in found])}
        return [r for r in found if r.item.id in keep]

    async def similar_peer_posts(
        self,
        profile_id: int,
        query: str,
        k: int = 5,
        *,
        platform: str | None = None,
        niche_key: str | None = None,
    ) -> list[Recalled[PeerPostOut]]:
        if self._peers is None:
            raise RuntimeError("Retriever built without a PeerPostStore")
        extra: dict[str, str | int | bool] = {}
        if platform:
            extra["platform"] = platform
        if niche_key:
            extra["niche_key"] = niche_key
        return await self._search(
            PEER_POSTS,
            "peer_post",
            profile_id,
            query,
            k,
            extra,
            self._peers.get_peer_posts,
        )

    async def similar_notes(
        self, profile_id: int, query: str, k: int = 5
    ) -> list[Recalled[MemoryNoteOut]]:
        if self._memory is None:
            raise RuntimeError("Retriever built without a MemoryStore")
        return await self._search(
            AGENT_MEMORY, "memory", profile_id, query, k, {}, self._memory.get_notes
        )

    async def _search(
        self,
        collection: str,
        kind: str,
        profile_id: int,
        query: str,
        k: int,
        extra: dict[str, str | int | bool],
        fetch: Callable[[Sequence[int]], Awaitable[list[R]]],
    ) -> list[Recalled[R]]:
        text = query.strip()
        if not text or k <= 0:
            return []
        where = {"profile_id": profile_id, **extra}

        def ask() -> list:
            vector = self._embedder.embed([text])[0]
            return self._vectors.query(collection, vector, k, where)

        hits = await asyncio.to_thread(ask)
        ranked: list[tuple[int, float]] = []
        for hit in hits:
            try:
                hit_kind, pk = parse_vector_id(hit.id)
            except ValueError:
                logger.warning(
                    "ignoring malformed vector id %r in %s", hit.id, collection
                )
                continue
            if hit_kind == kind:
                ranked.append((pk, hit.distance))
        if not ranked:
            return []
        rows = {row.id: row for row in await fetch([pk for pk, _ in ranked])}
        stale = [pk for pk, _ in ranked if pk not in rows]
        if stale:
            logger.warning(
                "%s: dropping %d vectors without a row", collection, len(stale)
            )
            await asyncio.to_thread(
                self._vectors.delete, collection, [vector_id(kind, pk) for pk in stale]
            )
        return [
            Recalled(rows[pk], distance)
            for pk, distance in ranked
            if pk in rows and rows[pk].profile_id == profile_id
        ]
