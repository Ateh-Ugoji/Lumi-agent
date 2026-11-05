"""``VideoAnalysisStore``: the analysis cache in ``video_analysis_records``.

A record hangs off a ``post_media`` row, so a URL that is not stored yet cannot be cached: it
is skipped (and costs one more analysis next time), never invented. The same video URL can sit
in several media rows (a repost); every one of them gets the record.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from apps.intelligence.models import VideoAnalysisRecord, VideoAnalysisStatus
from apps.intelligence.repos.aio import aio
from apps.profiles.models import PostMedia
from lumi_ai.ports import VideoAnalysis, VideoUnavailable
from lumi_ai.video.codec import from_dict, to_dict

logger = logging.getLogger(__name__)

MAX_ERROR_CHARS = 1_000


class VideoRepo:
    @aio
    def cached(
        self, media_urls: Sequence[str], *, provider: str, prompt_version: str
    ) -> dict[str, VideoAnalysis]:
        urls = list(dict.fromkeys(media_urls))
        if not urls:
            return {}
        rows = (
            VideoAnalysisRecord.objects.filter(
                media__url__in=urls,
                provider=provider,
                prompt_version=prompt_version,
                status=VideoAnalysisStatus.OK,
            )
            .select_related("media")
            .order_by("id")
        )
        found: dict[str, VideoAnalysis] = {}
        for row in rows:
            if row.media.url in found or not isinstance(row.result, dict):
                continue
            try:
                found[row.media.url] = from_dict(
                    row.result,
                    media_url=row.media.url,
                    provider=provider,
                    prompt_version=prompt_version,
                )
            except VideoUnavailable:
                logger.warning("stored video analysis %s no longer parses", row.pk)
        return found

    @aio
    def save(self, analyses: Sequence[VideoAnalysis], *, model: str) -> int:
        written = 0
        for analysis in analyses:
            for media in PostMedia.objects.filter(url=analysis.media_url):
                VideoAnalysisRecord.objects.update_or_create(
                    media=media,
                    provider=analysis.provider,
                    prompt_version=analysis.prompt_version,
                    defaults={
                        "model": model,
                        "status": VideoAnalysisStatus.OK,
                        "result": to_dict(analysis),
                        "error": "",
                    },
                )
                written += 1
        return written

    @aio
    def save_failure(
        self,
        media_url: str,
        *,
        provider: str,
        model: str,
        prompt_version: str,
        error: str,
    ) -> bool:
        stored = False
        for media in PostMedia.objects.filter(url=media_url):
            _, created = VideoAnalysisRecord.objects.get_or_create(
                media=media,
                provider=provider,
                prompt_version=prompt_version,
                defaults={
                    "model": model,
                    "status": VideoAnalysisStatus.FAILED,
                    "error": error[:MAX_ERROR_CHARS],
                },
            )
            if not created:  # an ok record stays; a failed one keeps its first reason
                VideoAnalysisRecord.objects.filter(
                    media=media,
                    provider=provider,
                    prompt_version=prompt_version,
                    status=VideoAnalysisStatus.FAILED,
                ).update(error=error[:MAX_ERROR_CHARS], model=model)
            stored = True
        return stored
