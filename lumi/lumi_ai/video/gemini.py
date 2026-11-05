"""Gemini adapter (``VIDEO_PROVIDER=gemini``): one ``generateContent`` call per video.

Plain REST through httpx, no SDK: Google is moving its SDKs to a new Interactions API and calls
``generateContent`` "legacy", so the adapter is one small file that can be replaced. The video is
downloaded here (``fetch.py``: public hosts only, size capped) and sent inline, because Gemini
fetches external URLs only up to 15 MB and the cap keeps the cost and the request predictable.
YouTube links go straight to Gemini (preview, no download). Use a **paid-tier** key: on the free
tier Google may use the content to improve its products.
"""

from __future__ import annotations

import base64
from typing import Any

import httpx

from lumi_ai.config import AIConfig
from lumi_ai.ports import VideoAnalysis, VideoUnavailable
from lumi_ai.video.codec import PROMPT_VERSION, build_prompt, parse_reply
from lumi_ai.video.fetch import Resolver, fetch_video, resolve_host
from lumi_ai.video.urls import is_youtube

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
PROVIDER = "gemini"
_BODY_CHARS = 200


def _redact(text: str, secret: str | None) -> str:
    return (text.replace(secret, "***") if secret else text)[:_BODY_CHARS]


class GeminiVideoAnalyzer:
    provider = PROVIDER

    def __init__(
        self,
        config: AIConfig,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        download_transport: httpx.AsyncBaseTransport | None = None,
        resolver: Resolver = resolve_host,
    ) -> None:
        if not config.video_api_key:
            raise VideoUnavailable("VIDEO_API_KEY is missing")
        self._config = config
        self._key = config.video_api_key
        self._transport = transport
        self._download_transport = download_transport
        self._resolver = resolver

    @property
    def model(self) -> str:
        return self._config.video_model

    async def _video_part(self, media_url: str) -> dict[str, Any]:
        if is_youtube(media_url):
            return {"file_data": {"file_uri": media_url}}
        fetched = await fetch_video(
            media_url,
            max_bytes=self._config.video_max_mb * 1_048_576,
            timeout=self._config.video_timeout_seconds,
            transport=self._download_transport,
            resolver=self._resolver,
        )
        return {
            "inline_data": {
                "mime_type": fetched.mime_type,
                "data": base64.b64encode(fetched.data).decode("ascii"),
            }
        }

    async def analyze(
        self, media_url: str, *, context: str | None = None
    ) -> VideoAnalysis:
        video = await self._video_part(media_url)
        body = {
            # The prompt goes after the video, as Google recommends.
            "contents": [{"parts": [video, {"text": build_prompt(context)}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "temperature": 0.2,
            },
        }
        try:
            async with httpx.AsyncClient(
                base_url=GEMINI_BASE_URL,
                headers={"x-goog-api-key": self._key},
                timeout=self._config.video_timeout_seconds,
                transport=self._transport,
            ) as http:
                response = await http.post(
                    f"/models/{self._config.video_model}:generateContent", json=body
                )
        except httpx.HTTPError as exc:
            raise VideoUnavailable(
                f"gemini request failed: {type(exc).__name__}"
            ) from None
        if response.status_code != 200:
            raise VideoUnavailable(
                f"gemini HTTP {response.status_code}: {_redact(response.text, self._key)}"
            )
        return parse_reply(
            _reply_text(response.json()),
            media_url=media_url,
            provider=PROVIDER,
            prompt_version=PROMPT_VERSION,
        )


def _reply_text(payload: Any) -> str:
    if not isinstance(payload, dict):
        raise VideoUnavailable("gemini returned an unexpected payload")
    block = (payload.get("promptFeedback") or {}).get("blockReason")
    if block:
        raise VideoUnavailable(f"gemini blocked the video ({block})")
    candidates = payload.get("candidates") or []
    if not candidates:
        raise VideoUnavailable("gemini returned no candidates")
    parts = (candidates[0].get("content") or {}).get("parts") or []
    texts = [
        p["text"]
        for p in parts
        if isinstance(p, dict)
        and isinstance(p.get("text"), str)
        and not p.get("thought")
    ]
    if not texts:
        reason = candidates[0].get("finishReason") or "no text"
        raise VideoUnavailable(f"gemini returned no text ({reason})")
    return "".join(texts)
