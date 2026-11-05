import threading
import uuid

import pytest
from django.db import connections

from apps.accounts.models import User
from apps.core import jobs
from apps.core.models import BackgroundJob

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def clean_registry(monkeypatch):
    monkeypatch.setattr(jobs, "_HANDLERS", {})


@pytest.fixture
def user():
    return User.objects.create_user("jobs@example.com")


def test_enqueue_creates_a_queued_row_and_nothing_runs_by_default(user):
    calls = []
    jobs.register("demo")(lambda ctx: calls.append(ctx) or {"ok": True})
    job_id, created = jobs.enqueue(user.pk, "demo", params={"a": 1})
    assert created
    assert BackgroundJob.objects.get(pk=job_id).status == "queued"
    assert calls == []


def test_dedupe_returns_the_active_job_then_allows_a_new_one_after_it_ends(user):
    first, created = jobs.enqueue(user.pk, "demo", dedupe_key="k")
    again, created_again = jobs.enqueue(user.pk, "demo", dedupe_key="k")
    assert (first, created, created_again) == (again, True, False)
    BackgroundJob.objects.filter(pk=first).update(status="succeeded")
    third, created_third = jobs.enqueue(user.pk, "demo", dedupe_key="k")
    assert created_third and third != first


def test_run_job_success_stores_result_and_progress(user):
    jobs.register("demo")(lambda ctx: {"seen": ctx.params["n"]})
    job_id, _ = jobs.enqueue(user.pk, "demo", params={"n": 3})
    assert jobs.run_job(job_id) == "succeeded"
    row = BackgroundJob.objects.get(pk=job_id)
    assert (row.result, row.progress) == ({"seen": 3}, 100)
    assert row.started_at and row.finished_at


def test_run_job_is_claimed_once(user):
    calls = []
    jobs.register("demo")(lambda ctx: calls.append(1))
    job_id, _ = jobs.enqueue(user.pk, "demo")
    assert jobs.run_job(job_id) == "succeeded"
    assert jobs.run_job(job_id) == "skipped"
    assert calls == [1]


def test_expected_failure_keeps_its_code_and_message(user):
    def handler(ctx):
        raise jobs.JobError("provider.down", "The provider is down.")

    jobs.register("demo")(handler)
    job_id, _ = jobs.enqueue(user.pk, "demo")
    assert jobs.run_job(job_id) == "failed"
    row = BackgroundJob.objects.get(pk=job_id)
    assert (row.error_code, row.error_message) == (
        "provider.down",
        "The provider is down.",
    )


def test_unexpected_failure_hides_the_exception_text(user):
    def handler(ctx):
        raise RuntimeError("secret-internal-detail")

    jobs.register("demo")(handler)
    job_id, _ = jobs.enqueue(user.pk, "demo")
    assert jobs.run_job(job_id) == "failed"
    row = BackgroundJob.objects.get(pk=job_id)
    assert row.error_code == "job.unexpected"
    assert "secret" not in row.error_message


def test_unknown_kind_fails_clearly(user):
    job_id, _ = jobs.enqueue(user.pk, "nobody.handles.this")
    jobs.run_job(job_id)
    assert BackgroundJob.objects.get(pk=job_id).error_code == "job.no_handler"


def test_registering_a_kind_twice_is_an_error():
    jobs.register("demo")(lambda ctx: None)
    with pytest.raises(RuntimeError):
        jobs.register("demo")(lambda ctx: None)


def test_get_job_is_scoped_to_the_owner(user):
    other = User.objects.create_user("other@example.com")
    job_id, _ = jobs.enqueue(user.pk, "demo")
    assert jobs.get_job(job_id, user.pk).pk == job_id
    assert jobs.get_job(job_id, other.pk) is None
    assert jobs.get_job("not-a-uuid", user.pk) is None
    assert jobs.get_job(uuid.uuid4(), user.pk) is None


def test_progress_is_clamped_and_only_while_running(user):
    job_id, _ = jobs.enqueue(user.pk, "demo")
    jobs.set_progress(job_id, 50)
    assert BackgroundJob.objects.get(pk=job_id).progress is None  # still queued
    BackgroundJob.objects.filter(pk=job_id).update(status="running")
    jobs.set_progress(job_id, 500)
    assert BackgroundJob.objects.get(pk=job_id).progress == 100


def test_eager_dispatch_runs_after_commit(
    user, settings, django_capture_on_commit_callbacks
):
    settings.LUMI_JOB_DISPATCH = "eager"
    jobs.register("demo")(lambda ctx: {"done": True})
    with django_capture_on_commit_callbacks(execute=True):
        job_id, _ = jobs.enqueue(user.pk, "demo")
    assert BackgroundJob.objects.get(pk=job_id).status == "succeeded"


@pytest.mark.django_db(transaction=True)
def test_two_workers_cannot_both_run_a_job():
    user = User.objects.create_user("race-jobs@example.com")
    runs = []
    jobs.register("demo")(lambda ctx: runs.append(1))
    job_id, _ = jobs.enqueue(user.pk, "demo")
    barrier = threading.Barrier(2)
    results = []

    def worker():
        try:
            barrier.wait()
            results.append(jobs.run_job(job_id))
        finally:
            connections.close_all()

    threads = [threading.Thread(target=worker) for _ in range(2)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(results) == ["skipped", "succeeded"]
    assert runs == [1]
