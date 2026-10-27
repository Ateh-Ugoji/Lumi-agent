"""Chroma behind the ``VectorStore`` port. Vectors and filter metadata only.

There is no ``documents`` argument anywhere in this module: the text of every vector lives
in PostgreSQL and is fetched by id (see ``retrieval.py``).
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from typing import Any

from lumi_ai.config import AIConfig
from lumi_ai.ports import Vector, VectorFilter, VectorHit
from lumi_ai.rag.collections import ALLOWED_METADATA
from lumi_ai.rag.errors import VectorIndexMismatch, VectorStoreError

logger = logging.getLogger(__name__)

EMBEDDER_KEY = "embedder"
_BATCH = 300  # Chroma Cloud caps one request at 300 records


def make_client(config: AIConfig) -> Any:
    """Chroma Cloud when ``CHROMA_API_KEY`` is set, otherwise a local persistent client."""
    import chromadb

    if config.chroma_api_key:
        return chromadb.CloudClient(
            api_key=config.chroma_api_key,
            tenant=config.chroma_tenant,
            database=config.chroma_database,
        )
    return chromadb.PersistentClient(path=config.chroma_path)


def _where(where: VectorFilter | None) -> dict[str, Any] | None:
    if not where:
        return None
    unknown = set(where) - ALLOWED_METADATA
    if unknown:
        raise ValueError(f"unsupported filter keys: {sorted(unknown)}")
    clauses = [{key: value} for key, value in where.items()]
    return clauses[0] if len(clauses) == 1 else {"$and": clauses}


class ChromaVectorStore:
    """``VectorStore`` over a Chroma client.

    ``embedder_name`` is written into each collection when it is created and checked every
    time it is opened, so swapping the embedder cannot silently mix two vector spaces.
    """

    def __init__(self, client: Any, embedder_name: str):
        self._client = client
        self._embedder_name = embedder_name
        self._checked: set[str] = set()

    def _collection(self, name: str) -> Any:
        try:
            collection = self._client.get_or_create_collection(
                name=name,
                embedding_function=None,  # we always pass vectors; never load Chroma's default model
                configuration={"hnsw": {"space": "cosine"}},
                metadata={EMBEDDER_KEY: self._embedder_name},
            )
        except Exception as exc:
            raise VectorStoreError(f"collection {name!r} unavailable: {exc}") from exc
        if name not in self._checked:
            built_by = (collection.metadata or {}).get(EMBEDDER_KEY)
            if built_by != self._embedder_name:
                raise VectorIndexMismatch(
                    f"collection {name!r} was built with {built_by!r}, now using "
                    f"{self._embedder_name!r}; run reindex_vectors"
                )
            self._checked.add(name)
        return collection

    def upsert(
        self,
        collection: str,
        ids: Sequence[str],
        embeddings: Sequence[Vector],
        metadatas: Sequence[VectorFilter],
    ) -> None:
        if not (len(ids) == len(embeddings) == len(metadatas)):
            raise ValueError("ids, embeddings and metadatas must have the same length")
        for meta in metadatas:
            unknown = set(meta) - ALLOWED_METADATA
            if unknown:
                raise ValueError(
                    f"metadata may only hold {sorted(ALLOWED_METADATA)}, got {sorted(unknown)}"
                )
        col = self._collection(collection)
        try:
            for start in range(0, len(ids), _BATCH):
                end = start + _BATCH
                col.upsert(
                    ids=list(ids[start:end]),
                    embeddings=[list(map(float, e)) for e in embeddings[start:end]],
                    metadatas=[dict(m) for m in metadatas[start:end]],
                )
        except Exception as exc:
            raise VectorStoreError(f"upsert into {collection!r} failed: {exc}") from exc

    def query(
        self,
        collection: str,
        embedding: Vector,
        k: int,
        where: VectorFilter | None = None,
    ) -> list[VectorHit]:
        flt = _where(where)
        col = self._collection(collection)
        try:
            res = col.query(
                query_embeddings=[list(map(float, embedding))],
                n_results=max(1, k),
                where=flt,
                include=["distances", "metadatas"],
            )
        except Exception as exc:
            raise VectorStoreError(f"query on {collection!r} failed: {exc}") from exc
        ids = (res.get("ids") or [[]])[0]
        distances = (res.get("distances") or [[]])[0]
        metas = (res.get("metadatas") or [[]])[0]
        return [
            VectorHit(id=i, distance=float(d), metadata=dict(m or {}))
            for i, d, m in zip(ids, distances, metas, strict=True)
        ]

    def delete(self, collection: str, ids: Sequence[str]) -> None:
        if not ids:
            return
        col = self._collection(collection)
        try:
            for start in range(0, len(ids), _BATCH):
                col.delete(ids=list(ids[start : start + _BATCH]))
        except Exception as exc:
            raise VectorStoreError(f"delete from {collection!r} failed: {exc}") from exc

    def reset(self, collection: str) -> None:
        try:
            self._client.delete_collection(collection)
        except Exception as exc:  # noqa: BLE001 - absent collection is fine; a real outage fails on the next line
            logger.debug("reset %s: %s", collection, exc)
        self._checked.discard(collection)
        self._collection(collection)

    def count(self, collection: str) -> int:
        return int(self._collection(collection).count())


def metadata_of(**fields: str | int | bool | None) -> Mapping[str, str | int | bool]:
    """Build filter metadata, dropping the ``None`` values Chroma would reject."""
    return {k: v for k, v in fields.items() if v is not None}
