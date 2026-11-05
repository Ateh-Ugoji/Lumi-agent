"""Speech-to-text on Groq's Whisper. Audio is transcribed and discarded; nothing is stored.

Text-to-speech is not served here: the Groq account exposes no TTS model, so the browser speaks
replies locally (legacy decision, kept).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import httpx
from openai import AsyncOpenAI

from lumi_ai.config import AIConfig
from lumi_ai.providers.urls import GROQ_BASE_URL, META_BASE_URL

# Whisper rejects uploads above 25 MB. Clips are seconds long; this guards a mis-sent file.
MAX_AUDIO_BYTES = 25 * 1024 * 1024


class AudioError(RuntimeError):
    """Transcription could not run or failed."""


class EmptyAudio(AudioError):
    """The upload had no bytes."""


class AudioTooLarge(AudioError):
    """The upload is over :data:`MAX_AUDIO_BYTES`."""


class AudioNotConfigured(AudioError):
    """``GROQ_API_KEY`` is not set."""


@dataclass(frozen=True, slots=True)
class Transcription:
    text: str
    model: str


class Transcriber:
    """Audio transcription client supporting Meta ASR (muse-voice-transcribe-1.0) and Groq Whisper.

    Built lazily so importing the package needs no key.
    """

    def __init__(self, config: AIConfig, client: Any | None = None) -> None:
        self._config = config
        self._client = client

    def _get_client(self) -> Any:
        if self._client is None:
            if not self._config.groq_api_key:
                raise AudioNotConfigured("Neither META_API_KEY nor GROQ_API_KEY is set")
            self._client = AsyncOpenAI(
                api_key=self._config.groq_api_key,
                base_url=GROQ_BASE_URL,
                timeout=self._config.llm_timeout_seconds,
                max_retries=0,
            )
        return self._client

    async def transcribe(
        self, audio: bytes, filename: str = "clip.wav", content_type: str = "audio/wav"
    ) -> Transcription:
        if not audio:
            raise EmptyAudio("empty audio upload")
        if len(audio) > MAX_AUDIO_BYTES:
            raise AudioTooLarge("audio too large (25 MB max)")

        if self._client is not None:
            model = self._config.whisper_model
            try:
                result = await self._client.audio.transcriptions.create(
                    model=model,
                    file=(filename, audio, content_type),
                    response_format="json",
                )
            except Exception as exc:
                raise AudioError(f"transcription failed: {type(exc).__name__}") from exc
            return Transcription(
                text=(getattr(result, "text", "") or "").strip(), model=model
            )

        if self._config.meta_api_key:
            return await self._transcribe_meta(audio, filename, content_type)

        client = self._get_client()
        model = self._config.whisper_model
        try:
            result = await client.audio.transcriptions.create(
                model=model,
                file=(filename, audio, content_type),
                response_format="json",
            )
        except Exception as exc:
            raise AudioError(f"transcription failed: {type(exc).__name__}") from exc
        return Transcription(
            text=(getattr(result, "text", "") or "").strip(), model=model
        )

    async def _transcribe_meta(
        self, audio: bytes, filename: str, content_type: str
    ) -> Transcription:
        model = self._config.meta_voice_model
        base_url = (self._config.meta_base_url or META_BASE_URL).rstrip("/")
        url = f"{base_url}/asr/transcribe"
        headers = {
            "Authorization": f"Bearer {self._config.meta_api_key}",
            "Accept": "application/json",
        }
        audio_encoding = "WAV" if "wav" in content_type.lower() else "MP3"
        req_payload = json.dumps({
            "model": model,
            "audioEncoding": audio_encoding,
            "mode": "PUSH_TO_TALK",
        })
        files = {
            "request": (None, req_payload, "application/json"),
            "audio": (filename, audio, content_type),
        }
        try:
            async with httpx.AsyncClient(timeout=self._config.llm_timeout_seconds) as http_client:
                resp = await http_client.post(url, headers=headers, files=files)
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:
            raise AudioError(f"transcription failed: {type(exc).__name__}") from exc

        return Transcription(
            text=(data.get("transcript") or "").strip(), model=model
        )
