"""``/api/v1/profiles/*``. See docs/CONTRATOS.md section 3.2."""

from __future__ import annotations

from django.db import transaction
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core import jobs
from apps.core.errors import ApiError
from apps.core.permissions import IsProfileOwner
from apps.profiles import services
from apps.profiles.serializers import CreateProfileSerializer, ListeningSerializer
from lumi_ai.ports import ListeningConfig

BOOTSTRAP_KIND = "profile.bootstrap"
REFRESH_KIND = "profile.refresh"


def _velocity(alert: services.AlertDetail) -> dict[str, float | None]:
    return {
        "likes_per_hour": alert["velocity"],
        "baseline_likes_per_hour": alert["baseline_velocity"],
    }


class _OwnedProfileView(APIView):
    """Base for routes with ``<profile_id>`` in the URL: the caller must own it."""

    permission_classes = [IsProfileOwner]


class ProfileListView(APIView):
    def get(self, request):
        return Response({"profiles": services.list_profile_summaries(request.user.pk)})

    def post(self, request):
        data = CreateProfileSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        try:
            with transaction.atomic():
                profile_id, created = services.get_or_create_profile(
                    request.user.pk,
                    data.validated_data["platform"],
                    data.validated_data["handle"],
                )
                job_id = None
                if created:
                    job_id, _ = jobs.enqueue(
                        request.user.pk,
                        BOOTSTRAP_KIND,
                        profile_id=profile_id,
                        dedupe_key=f"{BOOTSTRAP_KIND}:{profile_id}",
                    )
        except services.InvalidHandle:
            raise ApiError(
                "validation_error",
                "El handle no es válido para esa plataforma.",
                details={"field": "handle"},
            ) from None
        body = services.get_profile_summary(profile_id)
        body["job_id"] = str(job_id) if job_id else None
        return Response(
            body, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK
        )


class ProfileSelectView(_OwnedProfileView):
    def post(self, request, profile_id: int):
        return Response(services.select_info(profile_id))


class ProfileAnalyticsView(_OwnedProfileView):
    def get(self, request, profile_id: int):
        return Response(services.get_analytics(profile_id))


class ProfileRefreshView(_OwnedProfileView):
    def post(self, request, profile_id: int):
        job_id, _ = jobs.enqueue(
            request.user.pk,
            REFRESH_KIND,
            profile_id=profile_id,
            dedupe_key=f"{REFRESH_KIND}:{profile_id}",
        )
        return Response({"job_id": str(job_id)}, status=status.HTTP_202_ACCEPTED)


class UnreadAlertsView(_OwnedProfileView):
    def get(self, request, profile_id: int):
        alerts = [
            {
                "id": a["id"],
                "post_id": a["post_id"],
                "caption": a["caption"],
                "platform_post_id": a["platform_post_id"],
                "alerted_at": a["alerted_at"],
                "kind": a["kind"],
                "velocity": _velocity(a),
            }
            for a in services.unread_alert_details(profile_id)
        ]
        return Response({"alerts": alerts})


class DismissAlertView(_OwnedProfileView):
    def post(self, request, profile_id: int, alert_id: int):
        if not services.dismiss_alert(profile_id, alert_id):
            raise ApiError(
                "not_found",
                "Alerta no encontrada.",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        return Response(status=status.HTTP_204_NO_CONTENT)


def _listening_body(config: ListeningConfig) -> dict:
    return {
        "keywords": list(config.keywords),
        "enabled": config.enabled,
        "interval_minutes": config.interval_minutes,
    }


class ListeningView(_OwnedProfileView):
    def get(self, request, profile_id: int):
        return Response(_listening_body(services.get_listening(profile_id)))

    def put(self, request, profile_id: int):
        data = ListeningSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        config = ListeningConfig(
            profile_id=profile_id,
            keywords=tuple(data.validated_data["keywords"]),
            enabled=data.validated_data["enabled"],
            interval_minutes=data.validated_data.get("interval_minutes"),
        )
        try:
            saved = services.set_listening(config)
        except ValueError:
            raise ApiError(
                "validation_error", "Configuración de escucha no válida."
            ) from None
        return Response(_listening_body(saved))
