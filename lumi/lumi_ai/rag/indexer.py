"""Write side of the vector index: embed texts and store ``<type>:<id>`` vectors.

Blocking (the embedder and Chroma are); async callers wrap these in ``asyncio.to_thread``.
Only ids and filter metadata reach Chroma.
"""

from __future__ import annotations

from collections.abc import Sequence

from lumi_ai.ports import Embedder, MemoryNoteOut, PeerPostOut, PostOut, VectorStore
from lumi_ai.rag.collections import AGENT_MEMORY, PEER_POSTS, VOICE_CORPUS, vector_id
from lumi_ai.rag.vector_store import metadata_of
from lumi_ai.style.service import authentic_originals


class VectorIndexer:
    def __init__(self, embedder: Embedder, vectors: VectorStore):
        self._embedder = embedder
        self._vectors = vectors

    def _put(
        self,
        collection: str,
        ids: list[str],
        texts: list[str],
        metas: list[dict[str, str | int | bool]],
    ) -> int:
        if not ids:
            return 0
        embeddings = self._embedder.embed(texts)
        if len(embeddings) != len(ids):
            raise ValueError("the embedder returned a different number of vectors")
        self._vectors.upsert(collection, ids, embeddings, metas)
        return len(ids)

    def index_posts(self, posts: Sequence[PostOut]) -> int:
        """The user's own authentic originals only; replies, retweets and cut text teach nothing."""
        rows = authentic_originals(posts)
        return self._put(
            VOICE_CORPUS,
            [vector_id("post", p.id) for p in rows],
            [p.text.strip() for p in rows],
            [
                dict(
                    metadata_of(
                        profile_id=p.profile_id, platform=p.platform, kind=p.kind
                    )
                )
                for p in rows
            ],
        )

    def index_peer_posts(self, posts: Sequence[PeerPostOut]) -> int:
        rows = [p for p in posts if p.text and p.text.strip()]
        return self._put(
            PEER_POSTS,
            [vector_id("peer_post", p.id) for p in rows],
            [p.text.strip() for p in rows],
            [
                dict(
                    metadata_of(
                        profile_id=p.profile_id,
                        platform=p.platform,
                        niche_key=p.niche_key,
                    )
                )
                for p in rows
            ],
        )

    def index_notes(self, notes: Sequence[MemoryNoteOut]) -> int:
        rows = [n for n in notes if n.text.strip()]
        return self._put(
            AGENT_MEMORY,
            [vector_id("memory", n.id) for n in rows],
            [n.text.strip() for n in rows],
            [dict(metadata_of(profile_id=n.profile_id, kind=n.kind)) for n in rows],
        )

    def remove(self, collection: str, kind: str, pks: Sequence[int]) -> None:
        self._vectors.delete(collection, [vector_id(kind, pk) for pk in pks])
