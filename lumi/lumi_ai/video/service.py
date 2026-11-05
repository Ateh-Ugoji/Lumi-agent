"""Run the analyzer over a set of URLs with a cache, a per-run cap and honest failures.

* cached analyses (same media, provider and prompt version) are reused and cost nothing;
* at most ``config.video_max_per_run`` new analyses start per run, the rest are reported as
  skipped, never silently dropped;
* one failing video never stops the others, and every failure carries its reason;
* nothing is saved here: ``VideoBatch.fresh`` is returned so the caller stores it once the media
  rows exist (competitor posts are stored after tagging).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from lumi_ai.config import AIConfig
from lumi_ai.ports import (
    VideoAnalysis,
    VideoAnalysisStore,
    VideoAnalyzer,
    VideoUnavailable,
)
from lumi_ai.video.codec import PROMPT_VERSION

log = logging.getLogger(__name__)

CONCURRENCY = 2


@dataclass(slots=True)
class VideoBatch:
    results: dict[str, VideoAnalysis] = field(default_factory=dict)  # url -> analysis
    fresh: list[VideoAnalysis] = field(
        default_factory=list
    )  # analysed now (to be stored)
    failures: dict[str, str] = field(default_factory=dict)  # url -> reason
    skipped: dict[str, str] = field(default_factory=dict)  # url -> reason

    def notes(self) -> list[str]:
        """One plain line per failure or skip, for the tool output."""
        return [
            f"video {u}: {why}" for u, why in {**self.skipped, **self.failures}.items()
        ]


async def analyze_videos(
    urls: Sequence[str],
    analyzer: VideoAnalyzer,
    *,
    store: VideoAnalysisStore | None,
    config: AIConfig,
    provider: str,
    contexts: Mapping[str, str] | None = None,
) -> VideoBatch:
    """Analyse ``urls``; never raises for a provider failure."""
    batch = VideoBatch()
    unique = list(dict.fromkeys(urls))
    if not unique:
        return batch
    if store is not None:
        try:
            batch.results.update(
                await store.cached(
                    unique, provider=provider, prompt_version=PROMPT_VERSION
                )
            )
        except Exception as exc:  # noqa: BLE001 - a cache read must not stop the analysis
            log.warning("video cache read failed: %s", exc)
    todo = [u for u in unique if u not in batch.results]
    allowed, over = todo[: config.video_max_per_run], todo[config.video_max_per_run :]
    for url in over:
        batch.skipped[url] = (
            f"not analysed: the run already started {config.video_max_per_run} new video "
            "analyses (VIDEO_MAX_PER_RUN)"
        )
    gate = asyncio.Semaphore(CONCURRENCY)

    async def one(url: str) -> None:
        async with gate:
            try:
                analysis = await analyzer.analyze(
                    url, context=(contexts or {}).get(url)
                )
            except VideoUnavailable as exc:
                batch.failures[url] = str(exc) or "provider refused the call"
            except Exception as exc:  # noqa: BLE001 - reported per video, never fatal
                log.warning(
                    "video analysis crashed for %s: %s", url, type(exc).__name__
                )
                batch.failures[url] = f"unexpected error: {type(exc).__name__}"
            else:
                batch.results[url] = analysis
                batch.fresh.append(analysis)

    await asyncio.gather(*(one(u) for u in allowed))
    return batch


async def persist(
    batch: VideoBatch,
    store: VideoAnalysisStore | None,
    *,
    provider: str,
    model: str,
) -> None:
    """Store what ``batch`` learned. Failures to store are logged, never raised."""
    if store is None:
        return
    try:
        if batch.fresh:
            await store.save(batch.fresh, model=model)
        for url, error in batch.failures.items():
            await store.save_failure(
                url,
                provider=provider,
                model=model,
                prompt_version=PROMPT_VERSION,
                error=error,
            )
    except Exception as exc:  # noqa: BLE001 - the cache is an optimisation
        log.warning("video cache write failed: %s", exc)
