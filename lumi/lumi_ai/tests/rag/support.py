"""Test doubles for the RAG layer: a strict in-memory Chroma and a deterministic embedder."""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Sequence
from typing import Any

DIM = 64


class WordEmbedder:
    """Bag-of-words hashed into 64 dimensions: texts that share words are close."""

    name = "test-words-64"
    dimension = DIM

    def __init__(self) -> None:
        self.calls = 0

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        self.calls += 1
        out = []
        for text in texts:
            vec = [0.0] * DIM
            for word in re.findall(r"[a-z0-9]+", text.lower()):
                vec[int(hashlib.md5(word.encode()).hexdigest(), 16) % DIM] += 1.0
            norm = math.sqrt(sum(x * x for x in vec)) or 1.0
            out.append([x / norm for x in vec])
        return out


def _matches(meta: dict[str, Any], where: dict[str, Any] | None) -> bool:
    if not where:
        return True
    if "$and" in where:
        return all(_matches(meta, clause) for clause in where["$and"])
    return all(meta.get(k) == v for k, v in where.items())


class StrictCollection:
    """Accepts only what the port allows. ``documents=`` is a TypeError, as the plan demands."""

    def __init__(self, name: str, metadata: dict[str, Any]) -> None:
        self.name = name
        self.metadata = metadata
        self.rows: dict[str, tuple[list[float], dict[str, Any]]] = {}

    def upsert(self, *, ids, embeddings, metadatas) -> None:
        for i, e, m in zip(ids, embeddings, metadatas, strict=True):
            self.rows[i] = (list(e), dict(m))

    def query(self, *, query_embeddings, n_results, where=None, include=None):
        q = query_embeddings[0]
        scored = []
        for i, (e, m) in self.rows.items():
            if _matches(m, where):
                cos = sum(a * b for a, b in zip(q, e, strict=True))
                scored.append((1.0 - cos, i, m))
        scored.sort(key=lambda t: t[0])
        scored = scored[:n_results]
        return {
            "ids": [[i for _, i, _ in scored]],
            "distances": [[d for d, _, _ in scored]],
            "metadatas": [[m for _, _, m in scored]],
        }

    def delete(self, *, ids) -> None:
        for i in ids:
            self.rows.pop(i, None)

    def count(self) -> int:
        return len(self.rows)


class StrictChroma:
    def __init__(self) -> None:
        self.collections: dict[str, StrictCollection] = {}

    def get_or_create_collection(
        self, *, name, embedding_function=None, configuration=None, metadata=None
    ):
        if embedding_function is not None:
            raise AssertionError(
                "an embedding function would let Chroma embed text itself"
            )
        if name not in self.collections:
            self.collections[name] = StrictCollection(name, dict(metadata or {}))
        return self.collections[name]

    def delete_collection(self, name) -> None:
        if name not in self.collections:
            raise KeyError(name)
        del self.collections[name]
