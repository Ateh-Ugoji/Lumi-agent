"""Rebuild the vector index from PostgreSQL (the Django ``reindex_vectors`` command calls this).

Postgres is the source of truth, so the index can always be dropped and rebuilt.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable, Sequence

from lumi_ai.config import AIConfig
from lumi_ai.ports import MemoryStore, PeerPostStore, PostStore, VectorStore
from lumi_ai.rag.collections import AGENT_MEMORY, COLLECTIONS, PEER_POSTS, VOICE_CORPUS
from lumi_ai.rag.indexer import VectorIndexer

logger = logging.getLogger(__name__)


async def reindex_vectors(
    *,
    indexer: VectorIndexer,
    vectors: VectorStore,
    profile_ids: Iterable[int],
    config: AIConfig,
    posts: PostStore | None = None,
    peers: PeerPostStore | None = None,
    memory: MemoryStore | None = None,
    collections: Sequence[str] | None = None,
    reset: bool = True,
) -> dict[str, int]:
    """Re-embed every row of ``collections`` (default all) for ``profile_ids``.

    ``reset=True`` drops each collection first, which also clears vectors left behind by rows
    deleted in Postgres and changes of embedder. Pass every profile id when resetting.
    Returns ``{collection: vectors written}``.
    """
    wanted = tuple(collections) if collections else COLLECTIONS
    unknown = set(wanted) - set(COLLECTIONS)
    if unknown:
        raise ValueError(f"unknown collections: {sorted(unknown)}")
    sources = {VOICE_CORPUS: posts, PEER_POSTS: peers, AGENT_MEMORY: memory}
    missing = [c for c in wanted if sources[c] is None]
    if missing:
        raise ValueError(f"no store given for {missing}")
    ids = list(profile_ids)
    written = dict.fromkeys(wanted, 0)
    for collection in wanted:
        if reset:
            await asyncio.to_thread(vectors.reset, collection)
    for pid in ids:
        if VOICE_CORPUS in wanted:
            assert posts is not None
            rows = await posts.list_posts(pid, limit=config.rag_reindex_limit)
            written[VOICE_CORPUS] += await asyncio.to_thread(indexer.index_posts, rows)
        if PEER_POSTS in wanted:
            assert peers is not None
            peer_rows = await peers.list_peer_posts(pid, limit=config.rag_reindex_limit)
            written[PEER_POSTS] += await asyncio.to_thread(
                indexer.index_peer_posts, peer_rows
            )
        if AGENT_MEMORY in wanted:
            assert memory is not None
            notes = await memory.list_notes(pid, limit=config.rag_reindex_limit)
            written[AGENT_MEMORY] += await asyncio.to_thread(indexer.index_notes, notes)
    logger.info("reindexed %s for %d profiles", written, len(ids))
    return written
