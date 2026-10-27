"""``VIDEO_PROVIDER`` -> analyzer. Empty provider means the feature is off, not faked."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from lumi_ai.config import AIConfig
from lumi_ai.ports import VideoAnalyzer, VideoUnavailable
from lumi_ai.video.gemini import GeminiVideoAnalyzer

log = logging.getLogger(__name__)

PROVIDERS = ("gemini",)


@dataclass(frozen=True, slots=True)
class VideoStatus:
    enabled: bool
    reason: str  # why it is off, or what is on


def video_status(config: AIConfig) -> VideoStatus:
    provider = (config.video_provider or "").strip().lower()
    if not provider:
        return VideoStatus(False, "VIDEO_PROVIDER is empty: video analysis is off")
    if provider not in PROVIDERS:
        return VideoStatus(
            False,
            f"VIDEO_PROVIDER={provider!r} is not supported (choose one of: {', '.join(PROVIDERS)})",
        )
    if not config.video_api_key:
        return VideoStatus(
            False, f"VIDEO_PROVIDER={provider} but VIDEO_API_KEY is missing"
        )
    return VideoStatus(True, f"{provider} ({config.video_model})")


def build_video_analyzer(config: AIConfig) -> VideoAnalyzer | None:
    """The configured analyzer, or ``None`` when video analysis is off or misconfigured."""
    status = video_status(config)
    if not status.enabled:
        if (config.video_provider or "").strip():
            log.warning("video analysis is off: %s", status.reason)
        return None
    try:
        return GeminiVideoAnalyzer(config)
    except (
        VideoUnavailable
    ) as exc:  # pragma: no cover - video_status already checked the key
        log.warning("video analysis is off: %s", exc)
        return None
