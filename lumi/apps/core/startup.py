"""Startup checks shared by the ASGI, WSGI and Celery entry points."""

from __future__ import annotations

from django.conf import settings

from apps.core import keys


def check() -> None:
    """Fail on missing required keys (unless disabled by settings) and warn about optional ones."""
    if getattr(settings, "KEYS_ENFORCE_REQUIRED", True):
        keys.validate_required()
        keys.warn_optional()
