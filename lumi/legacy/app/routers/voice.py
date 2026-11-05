"""Voice I/O routes (phase 1 of the voice-chat integration).

Speech-to-text runs server-side on Groq's whisper (verified available on this
account: `whisper-large-v3`, `whisper-large-v3-turbo`). Text-to-speech is
deliberately *not* served here: the account exposes no TTS model, so the
browser speaks replies locally via `speechSynthesis` (see
`docs/codenamejo-integration.md` §3). Uploaded audio is transcribed and
discarded — nothing is persisted, and the payload never touches the DB.
"""

import logging
import time
from typing import Annotated

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from app.agent.providers import get_audio_provider

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/voice", tags=["voice"])

WHISPER_MODEL = "whisper-large-v3-turbo"
# Whisper rejects uploads above 25 MB; our clips are seconds long, so this is
# a guard against a mis-sent file, not a real limit.
MAX_AUDIO_BYTES = 25 * 1024 * 1024


class TranscribeResponse(BaseModel):
    text: str
    duration_ms: int


@router.post("/transcribe", response_model=TranscribeResponse)
async def transcribe(file: Annotated[UploadFile, File()]) -> TranscribeResponse:
    started = time.perf_counter()
    audio = await file.read()
    if not audio:
        raise HTTPException(status_code=422, detail="empty audio upload")
    if len(audio) > MAX_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail="audio too large (25 MB max)")

    client = get_audio_provider()
    try:
        result = await client.audio.transcriptions.create(
            model=WHISPER_MODEL,
            file=(file.filename or "clip.wav", audio, file.content_type or "audio/wav"),
            response_format="json",
        )
    except Exception as exc:
        logger.exception("voice transcribe failed (%s)", type(exc).__name__)
        raise HTTPException(
            status_code=502, detail=f"transcription failed: {type(exc).__name__}"
        ) from exc

    text = (getattr(result, "text", "") or "").strip()
    return TranscribeResponse(text=text, duration_ms=int((time.perf_counter() - started) * 1000))
