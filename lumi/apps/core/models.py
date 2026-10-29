import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.db.models.functions import Now

from apps.core.choices import JobStatus, LegacyOutcome
from apps.core.fields import EncryptedTextField


class TimestampedModel(models.Model):
    """``created_at`` and ``updated_at`` for tables that change after insert.

    ``created_at`` has a server-side default so a raw INSERT is valid too.
    """

    created_at = models.DateTimeField(db_default=Now(), editable=False)
    updated_at = models.DateTimeField(auto_now=True, db_default=Now(), editable=False)

    class Meta:
        abstract = True


ACTIVE_JOB_STATUSES = (JobStatus.QUEUED, JobStatus.RUNNING)


class BackgroundJob(models.Model):
    """Client-visible state of work that runs in Celery. See docs/SCHEMA.md section 6.2."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="background_jobs",
    )
    profile = models.ForeignKey(
        "profiles.SocialProfile",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="background_jobs",
    )
    kind = models.CharField(max_length=60)
    status = models.CharField(
        max_length=12, choices=JobStatus.choices, db_default=JobStatus.QUEUED
    )
    progress = models.SmallIntegerField(null=True, blank=True)
    params = models.JSONField(db_default={}, default=dict, blank=True)
    result = models.JSONField(null=True, blank=True)
    error_code = models.CharField(max_length=60, db_default="", blank=True)
    error_message = models.TextField(db_default="", blank=True)
    dedupe_key = models.CharField(max_length=160, null=True, blank=True)
    celery_task_id = models.CharField(max_length=155, db_default="", blank=True)
    created_at = models.DateTimeField(db_default=Now(), editable=False)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "background_jobs"
        constraints = [
            models.CheckConstraint(
                condition=Q(status__in=JobStatus.values),
                name="ck_background_jobs_status",
            ),
            models.CheckConstraint(
                condition=Q(progress__isnull=True)
                | (Q(progress__gte=0) & Q(progress__lte=100)),
                name="ck_background_jobs_progress",
            ),
            models.UniqueConstraint(
                fields=["dedupe_key"],
                condition=Q(dedupe_key__isnull=False)
                & Q(status__in=[s.value for s in ACTIVE_JOB_STATUSES]),
                name="uq_background_jobs_active_dedupe",
            ),
        ]
        indexes = [
            models.Index(
                fields=["user", "-created_at"], name="ix_background_jobs_user"
            ),
            models.Index(
                fields=["profile", "kind", "-created_at"],
                name="ix_background_jobs_profile",
            ),
            models.Index(
                fields=["status"],
                condition=Q(status__in=[s.value for s in ACTIVE_JOB_STATUSES]),
                name="ix_background_jobs_active",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.kind} {self.id} {self.status}"


class LegacyImportMap(models.Model):
    """Which legacy row became which new row. Makes the T8 importer repeatable."""

    source_table = models.CharField(max_length=80)
    source_pk = models.CharField(max_length=120)
    target_table = models.CharField(max_length=80)
    target_pk = models.BigIntegerField()
    outcome = models.CharField(
        max_length=10, choices=LegacyOutcome, default=LegacyOutcome.IMPORTED
    )
    # The whole legacy row as JSON, encrypted (it can hold tokens). Required whenever the
    # new tables do not hold everything the row said: merged, skipped or adjusted rows.
    payload = EncryptedTextField(null=True, blank=True)
    imported_at = models.DateTimeField(db_default=Now())

    class Meta:
        db_table = "legacy_import_map"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(outcome__in=["imported", "merged", "skipped"]),
                name="ck_legacy_import_map_outcome",
            ),
            models.CheckConstraint(
                condition=models.Q(outcome="imported")
                | models.Q(payload__isnull=False),
                name="ck_legacy_import_map_payload",
            ),
            models.UniqueConstraint(
                fields=["source_table", "source_pk", "target_table"],
                name="uq_legacy_import_map_source_target",
            ),
        ]
