"""Rank a niche report's frameworks by closeness to a topic, shared by advice and generation."""

from __future__ import annotations

import asyncio
import math
from collections.abc import Sequence

from lumi_ai.ports import Embedder, FrameworkOut


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


def framework_key(fw: FrameworkOut) -> str:
    return str(fw.payload.get("key") or fw.name)


def framework_text(fw: FrameworkOut) -> str:
    structure = fw.payload.get("structure")
    parts = [fw.title, fw.description, structure if isinstance(structure, str) else ""]
    return "\n".join(p for p in parts if p)


async def rank_frameworks(
    embedder: Embedder, topic: str, frameworks: Sequence[FrameworkOut]
) -> list[tuple[FrameworkOut, float]]:
    """Frameworks with their cosine similarity to ``topic``, closest first.

    The scores are raw cosine values, not calibrated probabilities. Embedding runs in a thread
    because the embedder is synchronous.
    """
    if not frameworks or not topic.strip():
        return []
    vectors = await asyncio.to_thread(
        embedder.embed, [topic, *[framework_text(f) for f in frameworks]]
    )
    scored = [
        (f, cosine(vectors[0], v)) for f, v in zip(frameworks, vectors[1:], strict=True)
    ]
    return sorted(scored, key=lambda pair: pair[1], reverse=True)
