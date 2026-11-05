from __future__ import annotations

import pytest

from lumi_ai.rag import ChromaVectorStore, VectorIndexMismatch, VectorStoreError
from lumi_ai.rag.collections import parse_vector_id, vector_id
from lumi_ai.tests.rag.support import StrictChroma

META = {"profile_id": 1, "platform": "x"}


def test_vector_ids_round_trip():
    assert vector_id("post", 42) == "post:42"
    assert parse_vector_id("peer_post:7") == ("peer_post", 7)
    for bad in ("42", "post:", "post:x", ":3"):
        with pytest.raises(ValueError):
            parse_vector_id(bad)


def test_the_fake_chroma_refuses_documents():
    """The guard this suite leans on: if the store ever passed documents=, this would raise."""
    col = StrictChroma().get_or_create_collection(name="c")
    with pytest.raises(TypeError):
        col.upsert(ids=["a"], embeddings=[[1.0]], metadatas=[{}], documents=["text"])  # type: ignore[call-arg]


def test_upsert_query_delete_and_filters():
    store = ChromaVectorStore(StrictChroma(), "e1")
    store.upsert(
        "voice_corpus",
        ["post:1", "post:2", "post:3"],
        [[1.0, 0.0], [0.0, 1.0], [1.0, 0.0]],
        [META, META, {"profile_id": 2, "platform": "x"}],
    )
    hits = store.query("voice_corpus", [1.0, 0.0], 5, {"profile_id": 1})
    assert [h.id for h in hits] == ["post:1", "post:2"]
    assert hits[0].distance == pytest.approx(0.0)
    both = store.query(
        "voice_corpus", [1.0, 0.0], 5, {"profile_id": 1, "platform": "x"}
    )
    assert len(both) == 2
    store.delete("voice_corpus", ["post:1", "missing:9"])
    assert store.count("voice_corpus") == 2


def test_metadata_is_limited_to_filter_keys():
    store = ChromaVectorStore(StrictChroma(), "e1")
    with pytest.raises(ValueError, match="text"):
        store.upsert(
            "voice_corpus", ["post:1"], [[1.0]], [{"profile_id": 1, "text": "leak"}]
        )
    with pytest.raises(ValueError):
        store.query("voice_corpus", [1.0], 1, {"text": "x"})
    with pytest.raises(ValueError):
        store.upsert("voice_corpus", ["a", "b"], [[1.0]], [META])


def test_another_embedder_cannot_reuse_a_collection():
    client = StrictChroma()
    ChromaVectorStore(client, "e1").upsert("voice_corpus", ["post:1"], [[1.0]], [META])
    with pytest.raises(VectorIndexMismatch, match="reindex_vectors"):
        ChromaVectorStore(client, "e2").query("voice_corpus", [1.0], 1)


def test_reset_rebuilds_with_the_current_embedder():
    client = StrictChroma()
    ChromaVectorStore(client, "e1").upsert("voice_corpus", ["post:1"], [[1.0]], [META])
    fresh = ChromaVectorStore(client, "e2")
    fresh.reset("voice_corpus")
    assert fresh.count("voice_corpus") == 0
    fresh.upsert(
        "voice_corpus", ["post:2"], [[1.0, 0.0]], [META]
    )  # a new dimension is fine


def test_backend_failures_become_vector_store_errors():
    class Broken(StrictChroma):
        def get_or_create_collection(self, **kw):
            raise ConnectionError("cloud down")

    with pytest.raises(VectorStoreError, match="cloud down"):
        ChromaVectorStore(Broken(), "e1").query("voice_corpus", [1.0], 1)


def test_the_real_chroma_engine_honours_the_same_contract(tmp_path):
    """Real local Chroma, our own vectors: no model, no network, no key."""
    chromadb = pytest.importorskip("chromadb")
    store = ChromaVectorStore(chromadb.PersistentClient(path=str(tmp_path)), "e1")
    store.upsert(
        "voice_corpus",
        ["post:1", "post:2", "post:3"],
        [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [1.0, 0.1, 0.0]],
        [META, META, {"profile_id": 2, "platform": "x"}],
    )
    hits = store.query(
        "voice_corpus", [1.0, 0.0, 0.0], 5, {"profile_id": 1, "platform": "x"}
    )
    assert [h.id for h in hits] == ["post:1", "post:2"]
    assert store.query("voice_corpus", [1.0, 0.0, 0.0], 5, {"profile_id": 9}) == []
    store.delete("voice_corpus", ["post:1"])
    assert store.count("voice_corpus") == 2
    with pytest.raises(VectorIndexMismatch):
        ChromaVectorStore(chromadb.PersistentClient(path=str(tmp_path)), "other").count(
            "voice_corpus"
        )
    store.reset("voice_corpus")
    assert store.count("voice_corpus") == 0


def test_no_module_of_the_rag_package_passes_documents():
    from pathlib import Path

    from lumi_ai import rag

    for path in Path(rag.__file__).parent.glob("*.py"):
        assert "documents=" not in path.read_text(), path.name
