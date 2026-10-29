"""One error format for the whole API: ``{"error": {"code", "message", "details"?}}``.

See docs/CONTRATOS.md section 2. Raise :class:`ApiError` for a domain error with its own code;
DRF and Django exceptions are translated here. Nothing in a response carries a trace, SQL or a key.
"""

from __future__ import annotations

import logging

from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.http import Http404, JsonResponse
from rest_framework import exceptions, status
from rest_framework.response import Response
from rest_framework.views import set_rollback

logger = logging.getLogger(__name__)


class ApiError(exceptions.APIException):
    """A domain error with a stable ``code``. ``details`` is optional and must be JSON."""

    status_code = status.HTTP_400_BAD_REQUEST
    default_code = "validation_error"

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int | None = None,
        details: dict | None = None,
    ) -> None:
        super().__init__(detail=message, code=code)
        if status_code is not None:
            self.status_code = status_code
        self.api_code = code
        self.details = details


def error_body(code: str, message: str, details: dict | None = None) -> dict:
    body: dict = {"code": code, "message": message}
    if details:
        body["details"] = details
    return {"error": body}


def _flatten(detail) -> dict | list | str:
    """Turn DRF's ErrorDetail structures into plain strings."""
    if isinstance(detail, dict):
        return {key: _flatten(value) for key, value in detail.items()}
    if isinstance(detail, list):
        return [_flatten(item) for item in detail]
    return str(detail)


def _message(detail) -> str:
    flat = _flatten(detail)
    if isinstance(flat, str):
        return flat
    if isinstance(flat, list) and flat and isinstance(flat[0], str):
        return flat[0]
    return "Datos inválidos."


def exception_handler(exc, context):
    headers: dict[str, str] = {}
    details: dict | None = None

    if isinstance(exc, ApiError):
        code, message, http_status, details = (
            exc.api_code,
            str(exc.detail),
            exc.status_code,
            exc.details,
        )
    elif isinstance(exc, exceptions.ValidationError):
        code, http_status = "validation_error", 400
        flat = _flatten(exc.detail)
        message = "Datos inválidos."
        if isinstance(flat, dict):
            details = flat
        else:
            message = _message(exc.detail)
    elif isinstance(exc, exceptions.ParseError):
        code, message, http_status = (
            "validation_error",
            "El cuerpo no es JSON válido.",
            400,
        )
    elif isinstance(exc, exceptions.AuthenticationFailed | exceptions.NotAuthenticated):
        code, message, http_status = "unauthenticated", str(exc.detail), 401
        if auth_header := getattr(exc, "auth_header", None):
            headers["WWW-Authenticate"] = auth_header
    elif isinstance(exc, exceptions.PermissionDenied | DjangoPermissionDenied):
        code, message, http_status = "forbidden", "No tienes permiso para esto.", 403
    elif isinstance(exc, exceptions.NotFound | Http404):
        code, message, http_status = "not_found", "No existe o no es tuyo.", 404
    elif isinstance(exc, exceptions.MethodNotAllowed):
        code, message, http_status = "method_not_allowed", str(exc.detail), 405
    elif isinstance(exc, exceptions.Throttled):
        code, message, http_status = "rate_limited", "Demasiadas peticiones.", 429
        if exc.wait is not None:
            headers["Retry-After"] = str(int(exc.wait) + 1)
            details = {"retry_after_seconds": int(exc.wait) + 1}
    elif isinstance(exc, exceptions.NotAcceptable | exceptions.UnsupportedMediaType):
        code, message, http_status = (
            "validation_error",
            str(exc.detail),
            exc.status_code,
        )
    elif isinstance(exc, exceptions.APIException):
        code, message, http_status = "internal_error", str(exc.detail), exc.status_code
    else:
        logger.exception("unhandled error in %s", context.get("view"), exc_info=exc)
        code, message, http_status = "internal_error", "Error interno.", 500

    set_rollback()
    return Response(
        error_body(code, message, details), status=http_status, headers=headers
    )


def not_found_view(request, exception=None):
    return JsonResponse(error_body("not_found", "Ruta no encontrada."), status=404)


def server_error_view(request):
    return JsonResponse(error_body("internal_error", "Error interno."), status=500)
