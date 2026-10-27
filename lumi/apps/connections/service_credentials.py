"""Staff-side management of ``services`` and ``service_credentials``.

Nothing here returns or logs a secret. The log line says which fields changed, never their values.
Nothing reads these rows yet to talk to a provider: the environment is still the only source
(docs/CONEXIONES.md, "Credenciales de la app").
"""

from __future__ import annotations

import logging
from typing import Any

from django.db import IntegrityError, transaction
from django.db.models import QuerySet

from apps.core.errors import ApiError

from .models import Service, ServiceCredential

logger = logging.getLogger(__name__)

SETTABLE = (
    "app_id",
    "app_secret",
    "label",
    "environment",
    "extra",
    "is_active",
    "expires_at",
)


def list_services() -> QuerySet[Service]:
    return Service.objects.order_by("code")


def list_credentials(
    *,
    service: str | None = None,
    environment: str | None = None,
    active: bool | None = None,
) -> QuerySet[ServiceCredential]:
    rows = ServiceCredential.objects.select_related("service").order_by(
        "service__code", "environment", "-is_active", "id"
    )
    if service:
        rows = rows.filter(service__code=service)
    if environment:
        rows = rows.filter(environment=environment)
    if active is not None:
        rows = rows.filter(is_active=active)
    return rows


def get_credential(pk: int) -> ServiceCredential:
    row = ServiceCredential.objects.select_related("service").filter(pk=pk).first()
    if row is None:
        raise ApiError(
            "not_found", "Credencial no encontrada.", status_code=404
        )
    return row


def _conflict() -> ApiError:
    return ApiError(
        "credentials.conflict",
        "Ya hay una credencial activa de ese servicio en ese entorno. "
        "Desactiva la otra primero.",
        status_code=409,
    )


def _audit(action: str, row: ServiceCredential, user, fields: list[str]) -> None:
    # Ids and field NAMES only. Never a value, never the secret.
    logger.info(
        "service credential %s: id=%s service=%s environment=%s fields=%s by_user=%s",
        action,
        row.pk,
        row.service.code,
        row.environment,
        ",".join(sorted(fields)),
        getattr(user, "pk", None),
    )


def create_credential(user, data: dict[str, Any]) -> ServiceCredential:
    service: Service = data["service"]
    fields = {name: data[name] for name in SETTABLE if name in data}
    try:
        with transaction.atomic():
            row = ServiceCredential.objects.create(
                service=service, updated_by=user, **fields
            )
    except IntegrityError:
        raise _conflict() from None
    row.service = service
    _audit("created", row, user, list(fields))
    return row


def update_credential(
    user, row: ServiceCredential, data: dict[str, Any]
) -> ServiceCredential:
    changed = [name for name in SETTABLE if name in data]
    for name in changed:
        setattr(row, name, data[name])
    row.updated_by = user
    try:
        with transaction.atomic():
            row.save()
    except IntegrityError:
        raise _conflict() from None
    _audit("updated", row, user, changed)
    return row


def delete_credential(user, row: ServiceCredential) -> None:
    _audit("deleted", row, user, [])
    row.delete()
