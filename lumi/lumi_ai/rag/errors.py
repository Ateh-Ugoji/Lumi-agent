from __future__ import annotations


class VectorStoreError(RuntimeError):
    """The vector index could not do what was asked. Postgres is unaffected."""


class EmbedderUnavailable(VectorStoreError):
    """The embedding model could not load (for example the first download failed)."""


class VectorIndexMismatch(VectorStoreError):
    """The collection was built by another embedder; run ``reindex_vectors`` to rebuild it."""
