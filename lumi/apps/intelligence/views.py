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
from django.db import transaction
from rest_framework import serializers, status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.choices import IngestSource, Platform
from apps.core.errors import ApiError
from apps.core.permissions import IsProfileOwner
from apps.core.throttles import ChatUserThrottle
from apps.intelligence.models import (
    Framework,
    FrameworkEvidence,
    NichePreference,
    NicheReport,
)
from apps.intelligence.serializers import (
    ActiveNichePreferenceSerializer,
    NicheReportIngestSerializer,
)
from apps.intelligence.wiring import get_wiring
from apps.profiles.models import MetricSnapshot, Post, SocialHandle, SocialProfile
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


class ActiveNichePreferenceView(APIView):
    """Retrieve active niche keywords and preferences for dynamic search."""

    permission_classes = [IsProfileOwner]
    throttle_classes = [ChatUserThrottle]

    def get(self, request):
        profile = getattr(request, "profile", None)
        if profile is None:
            profile = request.user.social_profiles.select_related("handle").first()
            if not profile:
                raise ApiError("not_found", "No hay perfiles configurados.")

        platform = profile.handle.platform if profile.handle else "x"
        pref = (
            NichePreference.objects.filter(profile=profile, is_active=True)
            .prefetch_related("keywords", "handles__handle")
            .first()
        )

        if pref:
            keywords = [k.keyword for k in pref.keywords.all()]
            handles = [
                h.handle.handle_display or h.handle.handle_normalized
                for h in pref.handles.all()
            ]
            niche_key = pref.niche_key
            title = pref.title
        else:
            niche_key = f"{platform}:global"
            title = f"{platform.capitalize()} Creator"
            keywords = ["marketing", "content creation", "growth"]
            handles = []

        resp_data = {
            "profile_id": profile.pk,
            "email": request.user.email,
            "niche_key": niche_key,
            "title": title,
            "keywords": keywords,
            "handles": handles,
            "is_active": bool(pref),
        }
        serializer = ActiveNichePreferenceSerializer(data=resp_data)
        serializer.is_valid(raise_exception=True)
        return Response(serializer.data)


class NicheReportIngestView(APIView):
    """Ingest multi-platform winner posts, frameworks, and metrics from automation."""

    permission_classes = [IsProfileOwner]
    throttle_classes = [ChatUserThrottle]

    @transaction.atomic
    def post(self, request):
        serializer = NicheReportIngestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        profile = getattr(request, "profile", None)
        if profile is None:
            raise ApiError("validation_error", "profile_id es obligatorio.")

        report = NicheReport.objects.create(
            profile=profile,
            query=data["query"],
            niche=data["niche"],
            status=data["status"],
            posts_analyzed=data["posts_analyzed"],
            winner_count=data["winner_count"],
            peers_analyzed=data["peers_analyzed"],
            report=data.get("report") or {},
            origin=data["origin"],
        )

        post_map: dict[str, Post] = {}
        for post_data in data.get("posts", []):
            platform = post_data["platform"].lower()
            if platform in Platform.values:
                raw_handle = post_data["author_handle"].lstrip("@").strip()
                handle_norm = raw_handle.lower()
                handle_obj, _ = SocialHandle.objects.get_or_create(
                    platform=platform,
                    handle_normalized=handle_norm,
                    defaults={
                        "handle_display": post_data["author_handle"],
                        "display_name": post_data.get("author_display_name", "") or handle_norm,
                        "avatar_url": post_data.get("author_avatar_url", "") or "",
                    },
                )
                post_obj, _ = Post.objects.get_or_create(
                    author=handle_obj,
                    platform_post_id=post_data["platform_post_id"][:64],
                    defaults={
                        "caption": post_data.get("caption", ""),
                        "url": post_data.get("url", ""),
                        "published_at": post_data.get("published_at"),
                        "source": IngestSource.XPOZ,
                    },
                )
                post_map[post_data["platform_post_id"]] = post_obj

                if any(
                    post_data.get(k) is not None
                    for k in ("likes", "comments", "reposts", "views")
                ):
                    MetricSnapshot.objects.create(
                        post=post_obj,
                        source=IngestSource.XPOZ,
                        likes=post_data.get("likes"),
                        comments=post_data.get("comments"),
                        shares=post_data.get("reposts"),
                        views=post_data.get("views"),
                    )

        created_frameworks = []
        for fw_data in data.get("frameworks", []):
            fw_obj = Framework.objects.create(
                report=report,
                name=fw_data["name"][:160],
                description=fw_data.get("description", ""),
                lift=fw_data.get("lift"),
                confidence=fw_data.get("confidence"),
                payload=fw_data.get("payload") or {},
                ordinal=fw_data.get("ordinal", 0),
            )
            created_frameworks.append(fw_obj)

            for pid in fw_data.get("evidence_platform_post_ids", []):
                post_rec = post_map.get(pid)
                if post_rec:
                    FrameworkEvidence.objects.get_or_create(
                        framework=fw_obj,
                        post=post_rec,
                    )

        return Response(
            {
                "ok": True,
                "report_id": report.pk,
                "frameworks_count": len(created_frameworks),
                "posts_saved": len(post_map),
            },
            status=status.HTTP_201_CREATED,
        )
