"""Service behind ``POST /api/v1/publish``.

The route never publishes on its own: a real post needs ``confirm=true`` and an
``Idempotency-Key``. The key is unique per profile (``publish_jobs``), so a retry returns the
stored result and sends nothing. ``dry_run`` validates the draft and touches no ledger.

Publishing goes through the profile's linked connected account. Instagram and TikTok are not
published from here yet: they would go through Post for Me, whose posting call is not built.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from asgiref.sync import async_to_sync

from apps.core.errors import ApiError
from apps.core.fields import TokenDecryptError
from apps.core.permissions import get_owned_profile
from apps.intelligence.models import RepurposeAttempt

from . import accounts
from .errors import (
    LiveDisabled,
    ProviderAuthError,
    ProviderUnavailable,
    SocialDataError,
    ValidationFailed,
)
from .models import AccountStatus, ConnectedAccount, PublishJob
from .providers.base import AccountInfo, PublishDraft
from .publishing import (
    ConfirmationRequired,
    IdempotencyConflict,
    Published,
    Publisher,
    PublishInProgress,
)
from .stores import DjangoPublishLedger

# Platform of the post -> provider that holds the credentials.
PROVIDER_FOR_PLATFORM = {"facebook": "meta", "linkedin": "linkedin", "x": "x"}
EXPIRY_MARGIN_SECONDS = 60


def resolve_text(profile, *, text: str | None, attempt_id: int | None, platform: str):
    """Return ``(text, attempt)``. The attempt must belong to the caller's own profile."""
    attempt = None
    if attempt_id is not None:
        attempt = (
            RepurposeAttempt.objects.select_related("request")
            .filter(pk=attempt_id, request__profile=profile)
            .first()
        )
        if attempt is None:
            raise ApiError("not_found", "Borrador no encontrado.", status_code=404)
        if attempt.platform != platform:
            raise ApiError(
                "validation_error",
                "El borrador es de otra plataforma.",
                details={"platform": [f"El borrador es para {attempt.platform}."]},
            )
    body = (text if text is not None else (attempt.output if attempt else "")).strip()
    return body, attempt


def pick_account(user, profile, provider: str) -> ConnectedAccount:
    try:
        row = ConnectedAccount.objects.filter(
            user=user, provider=provider, social_profile=profile
        ).first()
    except TokenDecryptError:
        accounts.quarantine_unreadable(user_id=user.pk, provider=provider)
        raise _reconnect(provider) from None
    if row is None:
        raise ApiError(
            "publish.not_connected",
            "Este perfil no tiene una cuenta conectada para publicar.",
            status_code=409,
            details={"provider": provider},
        )
    return row


def fresh_row(row: ConnectedAccount) -> ConnectedAccount:
    """Reconnect is needed for dead accounts. An expired token is refreshed once."""
    if row.status in (AccountStatus.REVOKED, AccountStatus.EXPIRED):
        raise _reconnect(row.provider)
    soon = (
        row.expires_at
        and (row.expires_at - datetime.now(UTC)).total_seconds() < EXPIRY_MARGIN_SECONDS
    )
    if soon:
        outcome = accounts.refresh_account(row.pk)
        if outcome not in ("refreshed",):
            if row.expires_at <= datetime.now(UTC):
                raise _reconnect(row.provider)
            return row
        row.refresh_from_db()
    return row


def _reconnect(provider: str) -> ApiError:
    return ApiError(
        "publish.reconnect_required",
        "La conexión caducó. Vuelve a conectar la cuenta.",
        status_code=409,
        details={"provider": provider},
    )


def job_for(profile_id: int, key: str) -> PublishJob | None:
    return PublishJob.objects.filter(profile_id=profile_id, idempotency_key=key).first()


def publish_post(
    user,
    *,
    profile_id: int,
    platform: str,
    text: str | None,
    attempt_id: int | None,
    link: str | None,
    confirm: bool,
    dry_run: bool,
    idempotency_key: str | None,
) -> dict[str, Any]:
    profile = get_owned_profile(user, profile_id)
    provider_name = PROVIDER_FOR_PLATFORM.get(platform)
    if provider_name is None:
        raise ApiError(
            "publish.unsupported_platform",
            "Por ahora solo se publica en X, LinkedIn y Facebook.",
            details={"platform": [platform]},
        )
    body, attempt = resolve_text(
        profile, text=text, attempt_id=attempt_id, platform=platform
    )
    key = (idempotency_key or "").strip()
    if not dry_run:
        if confirm is not True:
            raise ApiError(
                "publish.confirmation_required",
                "Publicar necesita confirm=true.",
            )
        if not key:
            raise ApiError(
                "publish.idempotency_key_required",
                "Falta la cabecera Idempotency-Key.",
            )

    row = fresh_row(pick_account(user, profile, provider_name))
    info = AccountInfo(
        external_id=row.external_account_id,
        display_name=row.display_name,
        handle=row.handle or None,
        status=row.status,
    )
    ledger = DjangoPublishLedger(
        platform=platform,
        text=body,
        connected_account_id=row.pk,
        attempt_id=attempt.pk if attempt else None,
    )
    try:
        outcome: Published = async_to_sync(Publisher(ledger).publish)(
            accounts.make_provider(provider_name),
            accounts.token_set(row),
            info,
            PublishDraft(text=body, link=link or None),
            scope=profile.pk,
            confirm=confirm,
            idempotency_key=key or None,
            dry_run=dry_run,
        )
    except SocialDataError as exc:
        raise _publish_error(exc) from exc

    result = outcome.result
    job = None if dry_run else job_for(profile.pk, key)
    return {
        "status": "dry_run" if result.dry_run else "done",
        "dry_run": result.dry_run,
        "replayed": outcome.replayed,
        "job_id": job.pk if job else None,
        "platform": platform,
        "external_post_id": result.external_post_id,
        "url": result.url,
        "estimated_cost_usd": result.estimated_cost_usd,
        "warnings": list(result.warnings),
    }


def _publish_error(exc: SocialDataError) -> ApiError:
    """Typed messages are safe to show: they never carry bodies, headers or URLs."""
    if isinstance(exc, ConfirmationRequired):
        return ApiError(
            "publish.confirmation_required", "Publicar necesita confirm=true."
        )
    if isinstance(exc, IdempotencyConflict):
        return ApiError(
            "conflict",
            "Esa Idempotency-Key ya se usó para otra publicación.",
            status_code=409,
        )
    if isinstance(exc, PublishInProgress):
        return ApiError(
            "publish.in_progress",
            "Esta publicación está en curso o su resultado no se conoce. "
            "Revisa la plataforma antes de reintentar.",
            status_code=409,
        )
    if isinstance(exc, ValidationFailed):
        return ApiError("validation_error", str(exc) or "Publicación no válida.")
    if isinstance(exc, LiveDisabled):
        return accounts.api_error_from(exc)
    if isinstance(exc, ProviderAuthError):
        return ApiError(
            "publish.provider_rejected",
            "La plataforma rechazó la publicación. Revisa permisos o vuelve a conectar.",
            status_code=502,
        )
    if isinstance(exc, ProviderUnavailable):
        return ApiError(
            "publish.outcome_unknown",
            "La plataforma no respondió y el post puede haberse publicado. "
            "Revisa la plataforma y no reintentes con la misma clave.",
            status_code=502,
        )
    return accounts.api_error_from(exc)
