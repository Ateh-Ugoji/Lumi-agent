"""``POST /repurpose`` and ``POST /voice/transcribe``.

Both are thin: validation here, the work in ``lumi_ai``. A failure is reported as itself (a code
and a short message); no field of a reply is ever filled in by a made-up value.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from asgiref.sync import async_to_sync
from rest_framework import serializers, status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.errors import ApiError
from apps.core.permissions import IsProfileOwner
from apps.core.throttles import ChatUserThrottle
from apps.intelligence.wiring import get_wiring
from apps.profiles.models import Post, SocialProfile
from lumi_ai.generation.flow import GenerationFailed, GenerationResult
from lumi_ai.generation.platforms import PLATFORMS
from lumi_ai.generation.types import GenerationBrief
from lumi_ai.providers.audio import (
    AudioError,
    AudioNotConfigured,
    AudioTooLarge,
    EmptyAudio,
    Transcriber,
)
from lumi_ai.providers.errors import LLMError

log = logging.getLogger(__name__)

#: Names clients may send for a network. Only ``twitter`` is an alias; anything else unknown is a 422.
PLATFORM_ALIASES = {"twitter": "x"}
MAX_SOURCE_CHARS = 8000
MAX_PHRASES = 20
MAX_PHRASE_CHARS = 200


class RepurposeSerializer(serializers.Serializer):
    profile_id = serializers.IntegerField(min_value=1)
    source_text = serializers.CharField(max_length=MAX_SOURCE_CHARS)
    platforms = serializers.ListField(
        child=serializers.CharField(max_length=20), min_length=1, max_length=5
    )
    must_keep_phrases = serializers.ListField(
        child=serializers.CharField(max_length=MAX_PHRASE_CHARS),
        required=False,
        default=list,
        max_length=MAX_PHRASES,
    )
    post_id = serializers.IntegerField(min_value=1, required=False, allow_null=True)

    def validate_platforms(self, value: list[str]) -> list[str]:
        out: list[str] = []
        for raw in value:
            name = PLATFORM_ALIASES.get(raw.strip().lower(), raw.strip().lower())
            if name not in PLATFORMS:
                raise serializers.ValidationError(
                    f"Red desconocida: {raw!r}. Usa una de: {', '.join(PLATFORMS)}."
                )
            if name not in out:
                out.append(name)
        return out

    def validate_source_text(self, value: str) -> str:
        if not value.strip():
            raise serializers.ValidationError("El texto no puede estar vacío.")
        return value


def _evaluation_body(result: GenerationResult) -> dict[str, Any] | None:
    ev = result.review.evaluation
    if ev is None:
        return None
    return {
        "decision": ev.decision,
        "judge": ev.judge,
        "scores": dict(ev.scores),
        "mean_score": ev.mean_score,
        "style_similarity": ev.style_similarity,
        "deterministic_failures": list(ev.deterministic_failures),
        "critique": ev.critique or None,
    }


def _ok(platform: str, result: GenerationResult) -> dict[str, Any]:
    attempt = result.attempt
    chosen = result.outcome.attempts[result.outcome.chosen]
    return {
        "platform": platform,
        "ok": True,
        "request_id": result.request_id,
        "attempt_id": attempt.id,
        "output": attempt.output,
        "must_keep_passed": attempt.must_keep_passed,
        "judge_verdict": attempt.judge_verdict,
        "judge_confidence": attempt.judge_confidence,
        "route_label": result.outcome.route_label,
        "fallback": chosen.is_fallback,
        "attempts": len(result.saved),
        "evaluation": _evaluation_body(result),
        "warnings": list(result.warnings),
        "error": None,
    }


def _failed(platform: str, code: str, message: str) -> dict[str, Any]:
    return {
        "platform": platform,
        "ok": False,
        "error": {"code": code, "message": message},
    }


async def _generate_one(
    platform: str, profile_id: int, data: dict[str, Any], post_id: int | None
) -> dict[str, Any]:
    wiring = get_wiring()
    brief = GenerationBrief(
        profile_id=profile_id,
        platform=platform,  # type: ignore[arg-type]
        mode="repurpose",
        source_text=data["source_text"],
        must_keep=tuple(data["must_keep_phrases"]),
        source_post_id=post_id,
    )
    try:
        result = await wiring.generation.run(brief, wiring.config)
    except GenerationFailed as exc:
        log.warning("repurpose to %s failed: %s", platform, exc)
        return _failed(
            platform, "generation_failed", "El modelo no dio un borrador utilizable."
        )
    except LLMError as exc:
        log.warning("repurpose to %s: providers failed: %s", platform, exc)
        return _failed(
            platform, "llm_unavailable", "Los modelos no responden ahora mismo."
        )
    return _ok(platform, result)


async def _generate_all(
    profile_id: int, data: dict[str, Any], post_id: int | None
) -> list[dict[str, Any]]:
    return list(
        await asyncio.gather(
            *(_generate_one(p, profile_id, data, post_id) for p in data["platforms"])
        )
    )


def _check_source_post(profile: SocialProfile, post_id: int) -> None:
    owns = Post.objects.filter(pk=post_id, author_id=profile.handle_id).exists()
    if not owns:
        raise ApiError(
            "not_found",
            "Ese post no es de este perfil.",
            status_code=status.HTTP_404_NOT_FOUND,
        )


class RepurposeView(APIView):
    permission_classes = [IsProfileOwner]
    throttle_classes = [ChatUserThrottle]

    def post(self, request):
        data = RepurposeSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        profile = getattr(request, "profile", None)
        if profile is None:  # pragma: no cover - profile_id is a required field
            raise ApiError("validation_error", "profile_id es obligatorio.")
        values = data.validated_data
        post_id = values.get("post_id")
        if post_id is not None:
            _check_source_post(profile, post_id)
        started = time.monotonic()
        results = async_to_sync(_generate_all)(profile.pk, values, post_id)
        body = {
            "profile_id": profile.pk,
            "results": results,
            "elapsed_ms": int((time.monotonic() - started) * 1000),
        }
        if not any(r["ok"] for r in results):
            return Response(body, status=status.HTTP_502_BAD_GATEWAY)
        return Response(body)


class TranscribeView(APIView):
    """Speech to text. The audio is read, sent to the provider and dropped; nothing is stored."""

    permission_classes = [IsProfileOwner]
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    throttle_classes = [ChatUserThrottle]

    def post(self, request):
        upload = request.FILES.get("file")
        if upload is None:
            raise ApiError(
                "validation_error",
                "Falta el archivo de audio (campo 'file').",
                details={"file": ["Este campo es obligatorio."]},
            )
        wiring = get_wiring()
        started = time.monotonic()
        try:
            result = async_to_sync(Transcriber(wiring.config).transcribe)(
                upload.read(),
                upload.name or "clip.wav",
                upload.content_type or "audio/wav",
            )
        except EmptyAudio:
            raise ApiError(
                "validation_error", "El audio está vacío.", status_code=422
            ) from None
        except AudioTooLarge:
            raise ApiError(
                "payload_too_large",
                "El audio supera los 25 MB.",
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            ) from None
        except AudioNotConfigured:
            raise ApiError(
                "voice.transcription_unavailable",
                "La transcripción no está configurada.",
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            ) from None
        except AudioError as exc:
            log.warning("transcription failed: %s", exc)
            raise ApiError(
                "voice.transcription_failed",
                "No se pudo transcribir el audio.",
                status_code=status.HTTP_502_BAD_GATEWAY,
            ) from None
        return Response(
            {
                "text": result.text,
                "duration_ms": int((time.monotonic() - started) * 1000),
            }
        )
