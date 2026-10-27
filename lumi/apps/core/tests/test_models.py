"""Constraint tests for background_jobs and legacy_import_map."""

import uuid

import pytest
from django.db import IntegrityError, transaction

from apps.accounts.models import User
from apps.core.models import BackgroundJob, LegacyImportMap
from apps.profiles.models import SocialHandle, SocialProfile

pytestmark = pytest.mark.django_db


@pytest.fixture
def user():
    return User.objects.create_user("jobs@example.com")


@pytest.fixture
def profile(user):
    handle = SocialHandle.objects.create(platform="x", handle_normalized="jobber")
    return SocialProfile.objects.create(user=user, handle=handle)


def test_job_defaults_come_from_the_database(user):
    job = BackgroundJob.objects.create(user=user, kind="profile.refresh")
    job.refresh_from_db()
    assert isinstance(job.id, uuid.UUID)
    assert job.status == "queued"
    assert job.params == {}
    assert job.error_code == "" and job.celery_task_id == ""
    assert job.created_at is not None


def test_job_status_must_be_known(user):
    with pytest.raises(IntegrityError), transaction.atomic():
        BackgroundJob.objects.create(user=user, kind="x.y", status="done")


@pytest.mark.parametrize("progress", [-1, 101])
def test_job_progress_range(user, progress):
    with pytest.raises(IntegrityError), transaction.atomic():
        BackgroundJob.objects.create(user=user, kind="x.y", progress=progress)


@pytest.mark.parametrize("progress", [None, 0, 100])
def test_job_progress_accepts_bounds_and_null(user, progress):
    BackgroundJob.objects.create(user=user, kind="x.y", progress=progress)


def test_only_one_active_job_per_dedupe_key(user, profile):
    BackgroundJob.objects.create(
        user=user, profile=profile, kind="profile.refresh", dedupe_key="refresh:1"
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        BackgroundJob.objects.create(
            user=user, profile=profile, kind="profile.refresh", dedupe_key="refresh:1"
        )


def test_dedupe_key_is_free_once_the_job_finishes(user, profile):
    first = BackgroundJob.objects.create(
        user=user, kind="profile.refresh", dedupe_key="refresh:1"
    )
    BackgroundJob.objects.filter(pk=first.pk).update(status="succeeded")
    BackgroundJob.objects.create(
        user=user, kind="profile.refresh", dedupe_key="refresh:1"
    )


def test_jobs_without_a_dedupe_key_never_collide(user):
    BackgroundJob.objects.create(user=user, kind="a.b")
    BackgroundJob.objects.create(user=user, kind="a.b")


def test_deleting_the_profile_deletes_its_jobs(user, profile):
    BackgroundJob.objects.create(user=user, profile=profile, kind="a.b")
    profile.delete()
    assert BackgroundJob.objects.count() == 0


def test_legacy_import_map_is_unique_per_source_and_target():
    LegacyImportMap.objects.create(
        source_table="profiles",
        source_pk="1",
        target_table="social_profiles",
        target_pk=7,
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        LegacyImportMap.objects.create(
            source_table="profiles",
            source_pk="1",
            target_table="social_profiles",
            target_pk=8,
        )
    # the same legacy row may map to a second table (profiles merges into handles + profiles)
    LegacyImportMap.objects.create(
        source_table="profiles",
        source_pk="1",
        target_table="social_handles",
        target_pk=3,
    )
