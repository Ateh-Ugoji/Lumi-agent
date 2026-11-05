"""Chroma-backed retrieval. Chroma holds vectors only; Postgres owns every text."""

from lumi_ai.rag.collections import AGENT_MEMORY, COLLECTIONS, PEER_POSTS, VOICE_CORPUS
from lumi_ai.rag.embedder import OnnxMiniLMEmbedder
from lumi_ai.rag.errors import (
    EmbedderUnavailable,
    VectorIndexMismatch,
    VectorStoreError,
)
from lumi_ai.rag.extractor import LLMMemoryExtractor, MemoryExtractionError
from lumi_ai.rag.indexer import VectorIndexer
from lumi_ai.rag.memory import MemoryService, RememberResult
from lumi_ai.rag.reindex import reindex_vectors
from lumi_ai.rag.retrieval import Recalled, Retriever
from lumi_ai.rag.vector_store import ChromaVectorStore, make_client

__all__ = [
    "AGENT_MEMORY",
    "COLLECTIONS",
    "PEER_POSTS",
    "VOICE_CORPUS",
    "ChromaVectorStore",
    "EmbedderUnavailable",
    "LLMMemoryExtractor",
    "MemoryExtractionError",
    "MemoryService",
    "OnnxMiniLMEmbedder",
    "Recalled",
    "RememberResult",
    "Retriever",
    "VectorIndexMismatch",
    "VectorIndexer",
    "VectorStoreError",
    "make_client",
    "reindex_vectors",
]
