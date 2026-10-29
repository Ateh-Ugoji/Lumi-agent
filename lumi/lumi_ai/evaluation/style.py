"""Style similarity: how close a draft is to the nearest posts the author really wrote.

The number is the mean cosine similarity of the draft to the author's ``k`` closest posts on the
platform (any platform when there are none), clamped to 0..1. It is a raw cosine, not a
calibrated probability: it is recorded with every evaluation and only gates a draft when
``quality_min_style_similarity`` is set above zero.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from lumi_ai.generation.types import GenerationBrief
from lumi_ai.rag.retrieval import Retriever

log = logging.getLogger(__name__)
EXAMPLE_CHARS = 400


@dataclass(frozen=True, slots=True)
class StyleReference:
    similarity: float | None
    examples: tuple[str, ...] = ()
    warning: str | None = None


class StyleReferencer:
    def __init__(self, retriever: Retriever | None, *, k: int = 3) -> None:
        self._retriever = retriever
        self._k = k

    async def reference(self, brief: GenerationBrief, text: str) -> StyleReference:
        if self._retriever is None or self._k <= 0:
            return StyleReference(
                None, warning="no corpus of the author's posts to compare with"
            )
        try:
            found = await self._retriever.similar_posts(
                brief.profile_id, text, self._k, platform=brief.platform
            )
            if not found:
                found = await self._retriever.similar_posts(
                    brief.profile_id, text, self._k
                )
        except Exception as exc:  # noqa: BLE001 - the comparison is optional evidence
            log.warning("style similarity unavailable: %s", exc)
            return StyleReference(None, warning=f"style comparison unavailable: {exc}")
        if not found:
            return StyleReference(
                None, warning="the author has no indexed posts to compare with"
            )
        mean_distance = sum(r.distance for r in found) / len(found)
        similarity = min(1.0, max(0.0, 1.0 - mean_distance))
        examples = tuple(" ".join(r.item.text.split())[:EXAMPLE_CHARS] for r in found)
        return StyleReference(round(similarity, 4), examples)
