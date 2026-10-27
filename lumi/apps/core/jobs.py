"""Client-visible background jobs: a registry of handlers, plus the state machine on ``BackgroundJob``.

Flow: a view calls :func:`enqueue`, which writes a ``queued`` row (deduplicated while one is active)
and hands the id to the dispatcher after the transaction commits. A worker calls :func:`run_job`,
which claims the row with one conditional ``UPDATE`` so a job never runs twice.

The dispatcher is chosen by ``LUMI_JOB_DISPATCH``:

* ``none`` (default): the row stays ``queued`` until something calls :func:`run_job` (T9: Celery).
* ``eager``: :func:`run_job` runs inline after commit. For tests and local work without a worker.

Handlers are registered with :func:`register` and take ``(job: JobContext) -> dict | None``. A handler
raises :class:`JobError` for an expected failure; any other exception is logged and stored as
``job.unexpected`` with no trace text (the client never sees internals).
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.core.choices import JobStatus
from apps.core.models import ACTIVE_JOB_STATUSES, BackgroundJob

logger = logging.getLogger(__name__)

__all__ = [
    "JobContext",
    "JobError",
    "enqueue",
    "get_job",
    "job_body",
    "register",
    "registered_kinds",
    "run_job",
    "set_progress",
]

ERROR_MESSAGE_MAX = 500


class JobError(Exception):
    """An expected failure. ``code`` and ``message`` are stored and shown to the client."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class JobContext:
    id: uuid.UUID
    user_id: int
    profile_id: int | None
    kind: str
    params: Mapping[str, Any]


Handler = Callable[[JobContext], "dict[str, Any] | None"]
_HANDLERS: dict[str, Handler] = {}


def register(kind: str) -> Callable[[Handler], Handler]:
    """Decorator. A kind is registered once; a second registration is a programming error."""

    def wrap(fn: Handler) -> Handler:
        if kind in _HANDLERS and _HANDLERS[kind] is not fn:
            raise RuntimeError(f"job kind {kind!r} is already registered")
        _HANDLERS[kind] = fn
        return fn

    return wrap


def registered_kinds() -> list[str]:
    return sorted(_HANDLERS)


def enqueue(
    user_id: int,
    kind: str,
    *,
    profile_id: int | None = None,
    params: Mapping[str, Any] | None = None,
    dedupe_key: str | None = None,
) -> tuple[uuid.UUID, bool]:
    """Create a ``queued`` job and dispatch it after commit. Returns ``(job_id, created)``.

    With a ``dedupe_key``, an active job with the same key is returned instead of a second one.
    The partial unique index decides, so two requests racing cannot both insert.
    """
    if dedupe_key is not None:
        existing = _active_by_key(dedupe_key)
        if existing is not None:
            return existing, False
    try:
        with transaction.atomic():
            job = BackgroundJob.objects.create(
                user_id=user_id,
                profile_id=profile_id,
                kind=kind,
                params=dict(params or {}),
                dedupe_key=dedupe_key,
            )
    except IntegrityError:
        existing = _active_by_key(dedupe_key) if dedupe_key is not None else None
        if existing is None:
            raise
        return existing, False
    transaction.on_commit(lambda: _dispatch(job.pk))
    return job.pk, True


def _active_by_key(dedupe_key: str) -> uuid.UUID | None:
    return (
        BackgroundJob.objects.filter(
            dedupe_key=dedupe_key, status__in=ACTIVE_JOB_STATUSES
        )
        .values_list("pk", flat=True)
        .first()
    )


def _dispatch(job_id: uuid.UUID) -> None:
    mode = getattr(settings, "LUMI_JOB_DISPATCH", "none")
    if mode == "eager":
        run_job(job_id)
    elif mode != "none":
        logger.warning(
            "unknown LUMI_JOB_DISPATCH %r; job %s stays queued", mode, job_id
        )


def get_job(job_id: uuid.UUID | str, user_id: int) -> BackgroundJob | None:
    """The job if it belongs to the user, else ``None`` (a stranger's id looks like a missing one)."""
    try:
        key = uuid.UUID(str(job_id))
    except ValueError:
        return None
    return BackgroundJob.objects.filter(pk=key, user_id=user_id).first()


def job_body(job: BackgroundJob) -> dict[str, Any]:
    """Body of ``GET /jobs/{id}`` (CONTRATOS 3.2)."""
    return {
        "id": str(job.pk),
        "kind": job.kind,
        "status": job.status,
        "progress": job.progress,
        "result": job.result,
        "error_code": job.error_code,
        "error_message": job.error_message,
        "created_at": job.created_at,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
    }


def set_progress(job_id: uuid.UUID, percent: int) -> None:
    BackgroundJob.objects.filter(pk=job_id, status=JobStatus.RUNNING).update(
        progress=max(0, min(100, int(percent)))
    )


def run_job(job_id: uuid.UUID) -> str:
    """Run one job. Returns the final status, or ``"skipped"`` when it was already claimed."""
    claimed = BackgroundJob.objects.filter(pk=job_id, status=JobStatus.QUEUED).update(
        status=JobStatus.RUNNING, started_at=timezone.now(), progress=0
    )
    if not claimed:
        return "skipped"
    job = BackgroundJob.objects.get(pk=job_id)
    handler = _HANDLERS.get(job.kind)
    if handler is None:
        _finish(
            job_id,
            JobStatus.FAILED,
            error_code="job.no_handler",
            error_message=f"No handler for {job.kind}",
        )
        return JobStatus.FAILED
    context = JobContext(job.pk, job.user_id, job.profile_id, job.kind, job.params)
    try:
        result = handler(context)
    except JobError as exc:
        _finish(
            job_id, JobStatus.FAILED, error_code=exc.code, error_message=exc.message
        )
        return JobStatus.FAILED
    except Exception:
        logger.exception("job %s (%s) crashed", job_id, job.kind)
        _finish(
            job_id,
            JobStatus.FAILED,
            error_code="job.unexpected",
            error_message="The job failed.",
        )
        return JobStatus.FAILED
    _finish(job_id, JobStatus.SUCCEEDED, result=result)
    return JobStatus.SUCCEEDED


def _finish(
    job_id: uuid.UUID,
    status: str,
    *,
    result: dict[str, Any] | None = None,
    error_code: str = "",
    error_message: str = "",
) -> None:
    BackgroundJob.objects.filter(pk=job_id, status=JobStatus.RUNNING).update(
        status=status,
        result=result,
        error_code=error_code,
        error_message=error_message[:ERROR_MESSAGE_MAX],
        finished_at=timezone.now(),
        progress=100 if status == JobStatus.SUCCEEDED else None,
    )
