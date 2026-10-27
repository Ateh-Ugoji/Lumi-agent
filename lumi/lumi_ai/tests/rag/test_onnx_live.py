"""Real local embedder + real Chroma on a temp dir. No key and no money, but it needs the one-time
79 MB ONNX model download, so it is ``live`` (run: LUMI_RUN_LIVE=1 uv run pytest -m live lumi_ai/tests/rag)."""

from __future__ import annotations

import chromadb
import pytest

from lumi_ai.rag import (
    VOICE_CORPUS,
    ChromaVectorStore,
    OnnxMiniLMEmbedder,
    Retriever,
    VectorIndexer,
)
from lumi_ai.tests.fakes import FakePosts, make_post

pytestmark = pytest.mark.live

TEXTS = {
    1: "Shipping our product launch on Friday, nervous but excited",
    2: "Coffee is the best debugging tool I know",
    3: "Pricing your SaaS: charge more than you think you should",
}


@pytest.mark.asyncio
async def test_real_embedder_ranks_by_meaning_and_survives_a_rebuild(tmp_path):
    embedder = OnnxMiniLMEmbedder()
    try:
        embedder.embed(["warm up"])
    except Exception as exc:  # noqa: BLE001 - model download blocked/offline: not a product failure
        pytest.skip(f"ONNX model not available: {exc}")
    posts = FakePosts([make_post(i, t) for i, t in TEXTS.items()])
    vectors = ChromaVectorStore(
        chromadb.PersistentClient(path=str(tmp_path)), embedder.name
    )
    VectorIndexer(embedder, vectors).index_posts(posts.posts)
    retriever = Retriever(embedder, vectors, posts=posts)

    found = await retriever.similar_posts(
        1, "how much should I charge for my software", 3
    )
    assert found[0].item.id == 3
    assert 0.0 <= found[0].distance < found[-1].distance <= 2.0
    assert vectors.count(VOICE_CORPUS) == 3

    reopened = ChromaVectorStore(
        chromadb.PersistentClient(path=str(tmp_path)), embedder.name
    )
    again = await Retriever(embedder, reopened, posts=posts).similar_posts(
        1, "software pricing", 1
    )
    assert again[0].item.id == 3
