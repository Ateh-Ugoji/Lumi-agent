"""Refresh tokens that expire soon. Run it from cron until Celery beat is configured."""

from django.core.management.base import BaseCommand

from apps.connections import accounts


class Command(BaseCommand):
    help = (
        "Refresh OAuth tokens that expire within 7 days. Prints counts, never tokens."
    )

    def handle(self, *args, **options):
        counts = accounts.refresh_due()
        self.stdout.write(f"refresh_connections: {counts or 'nothing due'}")
