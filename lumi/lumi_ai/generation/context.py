"""Gathers what the writer is told about the author: voice, their own similar posts, winning structures.

Every source is optional and every absence is reported in ``ContextUsed.warnings``; nothing is
made up to fill a gap. The context is kept small on purpose: Groq refuses requests above about
7,000 tokens, so examples and frameworks are counted and truncated by the configuration.
"""

from __future__ import annotations

import logging

from lumi_ai.competitors.ranking import framework_key, rank_frameworks
from lumi_ai.config import AIConfig
from lumi_ai.generation.types import ContextUsed, GenerationBrief
from lumi_ai.generation.writer import NO_VOICE, WriterContext, format_voice
from lumi_ai.ports import Embedder, ReportStore, VoiceStore
from lumi_ai.rag.retrieval import Retriever

log = logging.getLogger(__name__)
FRAMEWORK_CHARS = 300


def _clip(text: str, limit: int) -> str:
    text = " ".join(text.split()) if limit < 200 else text.strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


class ContextBuilder:
    def __init__(
        self,
        voice: VoiceStore,
        *,
        retriever: Retriever | None = None,
        reports: ReportStore | None = None,
        embedder: Embedder | None = None,
    ) -> None:
        self._voice = voice
        self._retriever = retriever
        self._reports = reports
        self._embedder = embedder

    async def build(
        self, brief: GenerationBrief, config: AIConfig
    ) -> tuple[WriterContext, ContextUsed]:
        warnings: list[str] = []
        voice_text, voice_name, version = await self._voice_for(brief, warnings)
        example_ids, examples = await self._examples(brief, config, warnings)
        frameworks = await self._frameworks(brief, config, warnings)
        context = WriterContext(
            voice_text, tuple(examples), tuple(t for _, t in frameworks)
        )
        used = ContextUsed(
            voice=voice_name,
            voice_version=version,
            example_post_ids=tuple(example_ids),
            frameworks=tuple(k for k, _ in frameworks),
            warnings=tuple(warnings),
        )
        return context, used

    async def _voice_for(
        self, brief: GenerationBrief, warnings: list[str]
    ) -> tuple[str, str, int | None]:
        voice = await self._voice.current_voice(brief.profile_id, brief.platform)
        name = brief.platform
        if voice is None:
            voice = await self._voice.current_voice(brief.profile_id, None)
            name = "general"
        if voice is None:
            warnings.append(
                "no voice profile yet: the draft is written in a neutral voice; "
                "learn the voice first (extract_voice_profile) for a draft that sounds like the author"
            )
            return NO_VOICE, "none", None
        return format_voice(voice.payload), name, voice.version

    async def _examples(
        self, brief: GenerationBrief, config: AIConfig, warnings: list[str]
    ) -> tuple[list[int], list[str]]:
        if (
            self._retriever is None
            or config.generation_examples <= 0
            or not brief.subject
        ):
            return [], []
        try:
            found = await self._retriever.similar_posts(
                brief.profile_id,
                brief.subject,
                config.generation_examples,
                platform=brief.platform,
            )
            if not found:  # nothing written on this network yet: any of their posts shows the voice
                found = await self._retriever.similar_posts(
                    brief.profile_id, brief.subject, config.generation_examples
                )
        except Exception as exc:  # noqa: BLE001 - examples are optional context
            log.warning("example retrieval failed: %s", exc)
            warnings.append(f"examples of the author's posts unavailable: {exc}")
            return [], []
        posts = [r.item for r in found]
        return [p.id for p in posts], [
            _clip(p.text, config.generation_example_chars) for p in posts
        ]

    async def _frameworks(
        self, brief: GenerationBrief, config: AIConfig, warnings: list[str]
    ) -> list[tuple[str, str]]:
        if (
            brief.mode != "topic"
            or self._reports is None
            or self._embedder is None
            or config.generation_frameworks <= 0
        ):
            return []
        try:
            report = await self._reports.latest_report(brief.profile_id)
            if report is None or report.status != "ok" or not report.frameworks:
                return []
            ranked = await rank_frameworks(
                self._embedder, brief.subject, report.frameworks
            )
        except Exception as exc:  # noqa: BLE001 - frameworks are optional context
            log.warning("framework ranking failed: %s", exc)
            warnings.append(f"niche frameworks unavailable: {exc}")
            return []
        return [
            (framework_key(f), _clip(f"{f.title}: {f.description}", FRAMEWORK_CHARS))
            for f, _ in ranked[: config.generation_frameworks]
        ]
