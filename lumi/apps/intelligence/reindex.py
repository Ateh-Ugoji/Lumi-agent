"""``reindex_vectors``: rebuild Chroma from PostgreSQL (the source of truth)."""

from __future__ import annotations

from collections.abc import Sequence

from apps.intelligence import repos
from apps.profiles.models import SocialProfile
from lumi_ai.config import AIConfig
from lumi_ai.ports import Embedder, VectorStore
from lumi_ai.rag import ChromaVectorStore, OnnxMiniLMEmbedder, VectorIndexer
from lumi_ai.rag.reindex import reindex_vectors
from lumi_ai.rag.vector_store import make_client


async def run_reindex(
    config: AIConfig,
    *,
    collections: Sequence[str] | None = None,
    profile_ids: Sequence[int] | None = None,
    reset: bool = True,
    embedder: Embedder | None = None,
    vectors: VectorStore | None = None,
) -> dict[str, int]:
    """Re-embed every stored row. ``embedder`` and ``vectors`` exist for tests; production builds
    the ONNX embedder and the Chroma store from ``config``."""
    from asgiref.sync import sync_to_async

    embedder = embedder or OnnxMiniLMEmbedder()
    vectors = vectors or ChromaVectorStore(make_client(config), embedder.name)
    if profile_ids is None:
        profile_ids = await sync_to_async(
            lambda: list(SocialProfile.objects.values_list("pk", flat=True)),
            thread_sensitive=True,
        )()
    return await reindex_vectors(
        indexer=VectorIndexer(embedder, vectors),
        vectors=vectors,
        profile_ids=profile_ids,
        config=config,
        posts=repos.PostRepo(),
        peers=repos.PeerPostRepo(),
        memory=repos.MemoryRepo(),
        collections=collections,
        reset=reset,
    )
