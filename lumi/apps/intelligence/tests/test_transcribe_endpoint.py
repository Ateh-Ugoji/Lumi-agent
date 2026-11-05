"""``POST /voice/transcribe`` over HTTP.

The real view, permission, throttle, error mapping and the real ``Transcriber`` run. Only the
Groq client is a double (it would cost quota): a fake injected in place of the network.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from apps.intelligence import views
from lumi_ai.config import AIConfig
from lumi_ai.providers.audio import MAX_AUDIO_BYTES, Transcriber

pytestmark = pytest.mark.urls("apps.intelligence.tests.urls")

URL = "/api/v1/voice/transcribe"
SECRET = "gsk_live_secret_value"


class FakeGroq:
    """Stands in for the OpenAI-compatible client Groq exposes."""

    def __init__(self, text=" hola mundo \n", error: Exception | None = None):
        self.calls: list[dict] = []
        self._text, self._error = text, error
        self.audio = SimpleNamespace(
            transcriptions=SimpleNamespace(create=self._create)
        )

    async def _create(self, **kwargs):
        self.calls.append(kwargs)
        if self._error:
            raise self._error
        return SimpleNamespace(text=self._text)


@pytest.fixture
def groq(monkeypatch) -> FakeGroq:
    """A configured key and a fake client behind the real ``Transcriber``."""
    fake = FakeGroq()
    config = AIConfig(groq_api_key=SECRET)
    monkeypatch.setattr(views, "get_wiring", lambda: SimpleNamespace(config=config))
    monkeypatch.setattr(views, "Transcriber", lambda cfg: Transcriber(cfg, client=fake))
    return fake


def send(api, profile, data=b"RIFFxxxx", name="a.wav", ctype="audio/wav", **extra):
    body = {"profile_id": profile.pk, **extra}
    if data is not None:
        body["file"] = SimpleUploadedFile(name, data, ctype)
    return api.post(URL, body, format="multipart")


class TestSuccess:
    def test_the_trimmed_text_and_the_timing_come_back(self, api, profile, groq):
        res = send(api, profile)
        assert res.status_code == 200
        body = res.json()
        assert body["text"] == "hola mundo"
        assert isinstance(body["duration_ms"], int) and body["duration_ms"] >= 0
        assert set(body) == {"text", "duration_ms"}

    def test_the_audio_goes_to_the_configured_model_with_its_name_and_type(
        self, api, profile, groq
    ):
        send(api, profile, b"RIFFdata", name="voz.m4a", ctype="audio/mp4")
        (call,) = groq.calls
        assert call["model"] == AIConfig().whisper_model
        assert call["file"] == ("voz.m4a", b"RIFFdata", "audio/mp4")

    def test_a_silent_clip_is_an_empty_text_not_an_error(self, api, profile, groq):
        groq._text = None
        res = send(api, profile)
        assert res.status_code == 200 and res.json()["text"] == ""

    def test_the_audio_is_not_stored(self, api, profile, groq, settings, tmp_path):
        settings.MEDIA_ROOT = tmp_path
        send(api, profile)
        assert list(tmp_path.iterdir()) == []

    def test_it_works_without_a_profile_id(self, api, groq):
        """The route is not tied to a profile; only a given ``profile_id`` is checked."""
        res = api.post(
            URL,
            {"file": SimpleUploadedFile("a.wav", b"RIFF", "audio/wav")},
            format="multipart",
        )
        assert res.status_code == 200 and res.json()["text"] == "hola mundo"


class TestNoKey:
    @pytest.fixture(autouse=True)
    def _no_key(self, monkeypatch):
        config = AIConfig(groq_api_key=None)
        monkeypatch.setattr(views, "get_wiring", lambda: SimpleNamespace(config=config))

    def test_the_real_transcriber_says_it_is_unavailable(self, api, profile):
        res = send(api, profile)
        assert res.status_code == 503
        assert res.json()["error"]["code"] == "voice.transcription_unavailable"

    def test_the_message_never_names_the_variable(self, api, profile):
        assert "GROQ" not in send(api, profile).content.decode()

    def test_an_empty_key_counts_as_no_key(self, api, profile, monkeypatch):
        config = AIConfig(groq_api_key="")
        monkeypatch.setattr(views, "get_wiring", lambda: SimpleNamespace(config=config))
        assert (
            send(api, profile).json()["error"]["code"]
            == "voice.transcription_unavailable"
        )


class TestProviderFailure:
    @pytest.mark.parametrize(
        "error",
        [RuntimeError(f"401 bad key {SECRET}"), TimeoutError("slow"), ValueError()],
    )
    def test_any_provider_error_is_a_502_without_its_text(
        self, api, profile, groq, error
    ):
        groq._error = error
        res = send(api, profile)
        assert res.status_code == 502
        assert res.json()["error"]["code"] == "voice.transcription_failed"
        text = res.content.decode()
        assert SECRET not in text and type(error).__name__ not in text

    def test_the_failure_is_logged_with_the_type_only(self, api, profile, groq, caplog):
        groq._error = RuntimeError(f"bad {SECRET}")
        with caplog.at_level("WARNING", logger=views.log.name):
            send(api, profile)
        assert "RuntimeError" in caplog.text and SECRET not in caplog.text


class TestAuth:
    def test_no_credentials_is_401(self, profile, groq):
        res = send(APIClient(), profile)
        assert res.status_code == 401
        assert groq.calls == []

    def test_a_bad_token_is_refused(self, profile, groq):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION="Bearer not-a-token")
        assert send(client, profile).status_code == 401
        assert groq.calls == []

    def test_another_users_profile_is_404_and_nothing_is_sent(
        self, stranger_api, profile, groq
    ):
        res = send(stranger_api, profile)
        assert res.status_code == 404 and groq.calls == []

    def test_a_profile_id_that_is_not_a_number_is_404(self, api, groq):
        res = api.post(
            URL,
            {
                "profile_id": "abc",
                "file": SimpleUploadedFile("a.wav", b"RIFF", "audio/wav"),
            },
            format="multipart",
        )
        assert res.status_code == 404 and groq.calls == []


class TestInvalidInput:
    def test_no_file_is_400_with_the_field_named(self, api, profile, groq):
        res = send(api, profile, data=None)
        assert res.status_code == 400
        error = res.json()["error"]
        assert error["code"] == "validation_error" and "file" in error["details"]
        assert groq.calls == []

    def test_a_file_field_that_is_text_is_not_a_file(self, api, profile, groq):
        res = send(api, profile, data=None, file="not a file")
        assert res.status_code == 400 and groq.calls == []

    def test_a_json_body_has_no_file(self, api, profile, groq):
        res = api.post(URL, {"profile_id": profile.pk, "file": "x"}, format="json")
        assert res.status_code == 400 and groq.calls == []

    def test_an_empty_file_is_422(self, api, profile, groq):
        res = send(api, profile, data=b"")
        assert (
            res.status_code == 422 and res.json()["error"]["code"] == "validation_error"
        )
        assert groq.calls == []

    def test_more_than_25_mb_is_413(self, api, profile, groq):
        res = send(api, profile, data=b"\0" * (MAX_AUDIO_BYTES + 1))
        assert (
            res.status_code == 413
            and res.json()["error"]["code"] == "payload_too_large"
        )
        assert groq.calls == []

    def test_exactly_25_mb_is_accepted(self, api, profile, groq):
        assert send(api, profile, data=b"\0" * MAX_AUDIO_BYTES).status_code == 200

    def test_get_is_not_allowed(self, api, groq):
        assert api.get(URL).status_code == 405
