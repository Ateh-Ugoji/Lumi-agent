"""``POST /repurpose`` and ``POST /voice/transcribe`` against the real database and repos.

Only the language model and the judge are doubles (they would cost money); the generation flow,
the evaluator, the ORM stores and the HTTP layer are the real ones.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from apps.intelligence import models as m
from apps.intelligence import views
from apps.intelligence.repos import RepurposeRepo
from apps.profiles import services
from lumi_ai import ports
from lumi_ai.config import AIConfig
from lumi_ai.evaluation.evaluator import Evaluator
from lumi_ai.evaluation.reviewer import QualityReviewer
from lumi_ai.generation.context import ContextBuilder
from lumi_ai.generation.enforcement import EnforcementReviewer
from lumi_ai.generation.flow import GenerationService
from lumi_ai.providers.audio import (
    AudioError,
    AudioNotConfigured,
    AudioTooLarge,
    EmptyAudio,
    Transcription,
)
from lumi_ai.providers.errors import AllProvidersFailed
from lumi_ai.tests.agent.harness import say
from lumi_ai.tests.evaluation.support import ScriptedScorer, result
from lumi_ai.tests.fakes import FakeVoice
from lumi_ai.tests.generation.support import FakeJudge, TierLLM, reply

pytestmark = pytest.mark.urls("apps.intelligence.tests.urls")

URL = "/api/v1/repurpose"
SRC = "We shipped the new dashboard today. See https://acme.io/new @acme"
GOOD = "Our new dashboard is live. https://acme.io/new @acme"
WHEN = datetime(2026, 10, 1, tzinfo=UTC)


def wire(monkeypatch, script, *, rounds=4):
    judge = FakeJudge(
        choice=["standard"] * rounds, noul=[{"preserves_meaning": 0.95}] * rounds
    )
    scorer = ScriptedScorer("jev", [result()] * rounds)
    service = GenerationService(
        TierLLM(script),
        ContextBuilder(FakeVoice()),
        QualityReviewer(EnforcementReviewer(judge), Evaluator([scorer])),
        RepurposeRepo(),
        judge=judge,
    )
    monkeypatch.setattr(
        views,
        "get_wiring",
        lambda: SimpleNamespace(generation=service, config=AIConfig()),
    )
    return service


def body(profile, **kw):
    return {
        "profile_id": profile.pk,
        "source_text": SRC,
        "platforms": ["linkedin"],
        **kw,
    }


class TestRepurpose:
    def test_a_rewrite_is_stored_with_its_attempt_and_evaluation(
        self, api, profile, monkeypatch
    ):
        wire(monkeypatch, [reply(GOOD)])
        res = api.post(URL, body(profile), format="json")
        assert res.status_code == 200, res.content
        [out] = res.json()["results"]
        assert out["ok"] and out["output"] == GOOD and out["platform"] == "linkedin"
        assert (
            out["must_keep_passed"] is True and out["evaluation"]["decision"] == "pass"
        )
        attempt = m.RepurposeAttempt.objects.get(pk=out["attempt_id"])
        assert attempt.request_id == out["request_id"] and attempt.output == GOOD
        assert m.GenerationEvaluation.objects.get(attempt=attempt).decision == "pass"

    def test_several_networks_give_one_result_each_and_twitter_means_x(
        self, api, profile, monkeypatch
    ):
        wire(monkeypatch, [reply(GOOD)] * 4)
        res = api.post(
            URL, body(profile, platforms=["twitter", "linkedin", "x"]), format="json"
        )
        assert res.status_code == 200, res.content
        assert [r["platform"] for r in res.json()["results"]] == ["x", "linkedin"]
        assert m.RepurposeRequest.objects.filter(profile=profile).count() == 2

    def test_the_source_post_is_linked_when_it_is_the_profiles_own(
        self, api, profile, monkeypatch
    ):
        post_id = services.upsert_posts(
            profile.handle_id, [ports.PostIn("x", "m1", SRC, WHEN)]
        ).post_ids[0]
        wire(monkeypatch, [reply(GOOD)])
        res = api.post(URL, body(profile, post_id=post_id), format="json")
        assert res.status_code == 200, res.content
        request = m.RepurposeRequest.objects.get(
            pk=res.json()["results"][0]["request_id"]
        )
        assert request.source_post_id == post_id

    def test_a_post_of_somebody_else_is_refused_and_nothing_is_stored(
        self, api, profile, monkeypatch
    ):
        other = services.get_or_create_handle("x", "someoneelse", origin="cache")
        foreign = services.upsert_posts(
            other, [ports.PostIn("x", "t1", "theirs", WHEN)]
        ).post_ids[0]
        wire(monkeypatch, [reply(GOOD)])
        res = api.post(URL, body(profile, post_id=foreign), format="json")
        assert res.status_code == 404 and res.json()["error"]["code"] == "not_found"
        assert m.RepurposeRequest.objects.count() == 0

    def test_an_unknown_network_is_a_validation_error_not_a_default(
        self, api, profile, monkeypatch
    ):
        wire(monkeypatch, [reply(GOOD)])
        res = api.post(URL, body(profile, platforms=["myspace"]), format="json")
        assert (
            res.status_code == 400 and res.json()["error"]["code"] == "validation_error"
        )
        assert m.RepurposeRequest.objects.count() == 0

    def test_empty_text_and_missing_profile_are_refused(
        self, api, profile, monkeypatch
    ):
        wire(monkeypatch, [reply(GOOD)])
        assert (
            api.post(URL, body(profile, source_text="  "), format="json").status_code
            == 400
        )
        no_profile = {"source_text": SRC, "platforms": ["x"]}
        assert api.post(URL, no_profile, format="json").status_code == 400

    def test_a_profile_of_another_user_is_not_found(
        self, stranger_api, profile, monkeypatch
    ):
        wire(monkeypatch, [reply(GOOD)])
        res = stranger_api.post(URL, body(profile), format="json")
        assert res.status_code == 404
        assert m.RepurposeRequest.objects.count() == 0

    def test_it_needs_a_login(self, profile, monkeypatch):
        from rest_framework.test import APIClient

        wire(monkeypatch, [reply(GOOD)])
        assert APIClient().post(URL, body(profile), format="json").status_code == 401

    def test_when_every_provider_fails_the_answer_says_so_without_the_detail(
        self, api, profile, monkeypatch, caplog
    ):
        class Down:
            async def complete(self, *a, **k):
                raise AllProvidersFailed(())

        service = wire(monkeypatch, [reply(GOOD)])
        service._writer._llm = Down()
        res = api.post(URL, body(profile), format="json")
        assert res.status_code == 502
        [out] = res.json()["results"]
        assert out["ok"] is False and out["error"]["code"] == "llm_unavailable"
        assert "all LLM providers failed" not in res.content.decode()
        assert m.RepurposeRequest.objects.count() == 0

    def test_a_model_that_never_gives_a_usable_draft_is_a_failure_not_a_fake(
        self, api, profile, monkeypatch
    ):
        wire(monkeypatch, [say("not json at all")] * 6)
        res = api.post(URL, body(profile), format="json")
        assert res.status_code == 502
        assert res.json()["results"][0]["error"]["code"] == "generation_failed"
        assert m.RepurposeRequest.objects.count() == 0


class FakeTranscriber:
    outcome: object = Transcription(text="hello there", model="whisper-large-v3-turbo")

    def __init__(self, config, client=None):
        pass

    async def transcribe(self, audio, filename="clip.wav", content_type="audio/wav"):
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


class TestTranscribe:
    URL = "/api/v1/voice/transcribe"

    @pytest.fixture(autouse=True)
    def _wiring(self, monkeypatch):
        monkeypatch.setattr(
            views, "get_wiring", lambda: SimpleNamespace(config=AIConfig())
        )
        monkeypatch.setattr(views, "Transcriber", FakeTranscriber)

    def upload(self, api, profile, data=b"RIFFxxxx"):
        from django.core.files.uploadedfile import SimpleUploadedFile

        return api.post(
            self.URL,
            {
                "profile_id": profile.pk,
                "file": SimpleUploadedFile("a.wav", data, "audio/wav"),
            },
            format="multipart",
        )

    def test_the_text_comes_back(self, api, profile):
        res = self.upload(api, profile)
        assert res.status_code == 200 and res.json()["text"] == "hello there"

    @pytest.mark.parametrize(
        ("error", "status", "code"),
        [
            (EmptyAudio("x"), 422, "validation_error"),
            (AudioTooLarge("x"), 413, "payload_too_large"),
            (
                AudioNotConfigured("GROQ_API_KEY is not set"),
                503,
                "transcription_unavailable",
            ),
            (AudioError("transcription failed: APIError"), 502, "transcription_failed"),
        ],
    )
    def test_each_failure_has_its_status_and_code(
        self, api, profile, error, status, code
    ):
        FakeTranscriber.outcome = error
        try:
            res = self.upload(api, profile)
        finally:
            FakeTranscriber.outcome = Transcription(text="hello there", model="m")
        assert res.status_code == status and res.json()["error"]["code"] == code
        assert "GROQ_API_KEY" not in res.content.decode()

    def test_no_file_is_a_validation_error(self, api, profile):
        res = api.post(self.URL, {"profile_id": profile.pk}, format="multipart")
        assert res.status_code == 400

    def test_a_stranger_cannot_use_another_users_profile(self, stranger_api, profile):
        res = self.upload(stranger_api, profile)
        assert res.status_code == 404
