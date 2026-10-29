"""Test doubles for video analysis. Never built by ``factory.py``: production has no fake path."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from lumi_ai.ports import VideoAnalysis, VideoUnavailable
from lumi_ai.video.codec import PROMPT_VERSION


def sample_analysis(url: str, **overrides: object) -> VideoAnalysis:
    values: dict[str, object] = {
        "media_url": url,
        "provider": "fake",
        "prompt_version": PROMPT_VERSION,
        "duration_seconds": 42.0,
        "hook_first_3s": "A founder says 'I lost 10k in a week' to camera.",
        "transcript": "I lost 10k in a week. Here is what I changed.",
        "on_screen_text": ("10k in a week", "follow for part 2"),
        "cut_count": 14,
        "pace": "fast",
        "has_captions": True,
        "call_to_action": "Follow for part 2",
        "format": "talking_head",
    }
    values.update(overrides)
    return VideoAnalysis(**values)  # type: ignore[arg-type]


class FakeVideoAnalyzer:
    """Returns ``results[url]`` (or a default sample); raises ``VideoUnavailable`` for ``failing``."""

    provider = "fake"

    def __init__(
        self,
        results: Mapping[str, VideoAnalysis] | None = None,
        *,
        failing: Mapping[str, str] | None = None,
    ) -> None:
        self._results = dict(results or {})
        self._failing = dict(failing or {})
        self.calls: list[tuple[str, str | None]] = []

    async def analyze(
        self, media_url: str, *, context: str | None = None
    ) -> VideoAnalysis:
        self.calls.append((media_url, context))
        if media_url in self._failing:
            raise VideoUnavailable(self._failing[media_url])
        return self._results.get(media_url) or sample_analysis(media_url)


class InMemoryVideoStore:
    """``VideoAnalysisStore`` over dicts; ``known`` limits which URLs "have a media row"."""

    def __init__(self, known: Sequence[str] | None = None) -> None:
        self.known = None if known is None else set(known)
        self.rows: dict[tuple[str, str, str], VideoAnalysis] = {}
        self.failures: dict[tuple[str, str, str], str] = {}

    def _has_row(self, url: str) -> bool:
        return self.known is None or url in self.known

    async def cached(
        self, media_urls: Sequence[str], *, provider: str, prompt_version: str
    ) -> dict[str, VideoAnalysis]:
        return {
            u: row
            for u in media_urls
            if (row := self.rows.get((u, provider, prompt_version)))
        }

    async def save(self, analyses: Sequence[VideoAnalysis], *, model: str) -> int:
        written = 0
        for a in analyses:
            if self._has_row(a.media_url):
                self.rows[(a.media_url, a.provider, a.prompt_version)] = a
                written += 1
        return written

    async def save_failure(
        self,
        media_url: str,
        *,
        provider: str,
        model: str,
        prompt_version: str,
        error: str,
    ) -> bool:
        key = (media_url, provider, prompt_version)
        if not self._has_row(media_url) or key in self.rows:
            return False
        self.failures[key] = error
        return True
