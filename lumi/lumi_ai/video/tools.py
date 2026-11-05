"""``analyze_video``: read a video the user pasted. Absent from the registry while video is off."""

from __future__ import annotations

from typing import Any

from lumi_ai.config import AIConfig
from lumi_ai.ports import VideoAnalysisStore, VideoAnalyzer
from lumi_ai.tools.registry import ToolContext, ToolSpec
from lumi_ai.video.codec import to_dict
from lumi_ai.video.service import analyze_videos, persist
from lumi_ai.video.urls import is_http_url


def build(
    analyzer: VideoAnalyzer | None,
    store: VideoAnalysisStore | None,
    config: AIConfig,
) -> list[ToolSpec]:
    """No tool at all without an analyzer, so the model never offers what is switched off."""
    if analyzer is None:
        return []
    provider = getattr(analyzer, "provider", None) or (config.video_provider or "")

    async def analyze_video(ctx: ToolContext, url: str) -> dict[str, Any]:
        if not is_http_url(url):
            return {"error": "give the full http(s) link of the video"}
        batch = await analyze_videos(
            [url], analyzer, store=store, config=config, provider=provider
        )
        await persist(batch, store, provider=provider, model=config.video_model)
        analysis = batch.results.get(url)
        if analysis is None:
            reason = {**batch.failures, **batch.skipped}.get(url, "no result")
            return {"error": f"the video could not be analysed: {reason}"}
        return {
            "url": url,
            "from_cache": analysis not in batch.fresh,
            **to_dict(analysis),
        }

    return [
        ToolSpec(
            name="analyze_video",
            description=(
                "Watch and listen to one public video link the user gave (X, Instagram, TikTok, "
                "YouTube or a direct .mp4) and report its first 3 seconds, transcript, on-screen "
                "text, cuts, pace, captions, call to action and format. Costs provider credits; "
                "only use it on a link the user supplied."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "Full link to the video."}
                },
                "required": ["url"],
            },
            handler=analyze_video,
            cost="credits",
            cache_ttl=0,
        )
    ]
