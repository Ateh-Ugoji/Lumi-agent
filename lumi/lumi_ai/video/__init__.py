"""Video analysis (T10). Off unless ``VIDEO_PROVIDER`` and ``VIDEO_API_KEY`` are set."""

from lumi_ai.video.codec import PROMPT_VERSION, for_tagging
from lumi_ai.video.factory import build_video_analyzer, video_status
from lumi_ai.video.service import VideoBatch, analyze_videos, persist
from lumi_ai.video.urls import looks_like_video, video_urls

__all__ = [
    "PROMPT_VERSION",
    "VideoBatch",
    "analyze_videos",
    "build_video_analyzer",
    "for_tagging",
    "looks_like_video",
    "persist",
    "video_status",
    "video_urls",
]
