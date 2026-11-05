"""Tests for the /voice routes (STT only — TTS is browser-local in phase 1)."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import voice


def _app_client() -> TestClient:
    app = FastAPI()
    app.include_router(voice.router)
    return TestClient(app)


def _fake_groq(text: str = "", side_effect: Exception | None = None):
    create = AsyncMock(side_effect=side_effect) if side_effect else AsyncMock(return_value=SimpleNamespace(text=text))
    return SimpleNamespace(audio=SimpleNamespace(transcriptions=SimpleNamespace(create=create)))


def test_transcribe_happy_path(monkeypatch):
    fake = _fake_groq(text="  do a fresh recon  ")
    monkeypatch.setattr(voice, "get_audio_provider", lambda: fake)

    res = _app_client().post(
        "/voice/transcribe", files={"file": ("clip.wav", b"RIFF-fake-wav-bytes", "audio/wav")}
    )

    assert res.status_code == 200
    body = res.json()
    assert body["text"] == "do a fresh recon"  # trimmed
    assert body["duration_ms"] >= 0
    # the provider got the raw bytes with a filename + content type
    _, kwargs = fake.audio.transcriptions.create.call_args
    assert kwargs["model"] == voice.WHISPER_MODEL
    assert kwargs["file"][1] == b"RIFF-fake-wav-bytes"


def test_transcribe_rejects_empty_upload():
    res = _app_client().post("/voice/transcribe", files={"file": ("clip.wav", b"", "audio/wav")})
    assert res.status_code == 422


def test_transcribe_provider_failure_is_honest(monkeypatch):
    fake = _fake_groq(side_effect=RuntimeError("groq down"))
    monkeypatch.setattr(voice, "get_audio_provider", lambda: fake)

    res = _app_client().post(
        "/voice/transcribe", files={"file": ("clip.wav", b"RIFF-fake-wav-bytes", "audio/wav")}
    )

    assert res.status_code == 502
    assert "RuntimeError" in res.json()["detail"]


def test_transcribe_oversized_upload_rejected(monkeypatch):
    fake = _fake_groq(text="never reached")
    monkeypatch.setattr(voice, "get_audio_provider", lambda: fake)

    big = b"x" * (voice.MAX_AUDIO_BYTES + 1)
    res = _app_client().post("/voice/transcribe", files={"file": ("clip.wav", big, "audio/wav")})
    assert res.status_code == 413
