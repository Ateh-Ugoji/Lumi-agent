"""Celery task for the token refresh. Beat wiring belongs to ARCHITECT (config/celery.py)."""

from __future__ import annotations

from celery import shared_task

from . import accounts


@shared_task(name="connections.refresh_expiring")
def refresh_expiring_connections() -> dict[str, int]:
    return accounts.refresh_due()
