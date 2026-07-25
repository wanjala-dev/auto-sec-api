"""Tests for the generic background-job progress reporter.

The realtime publish is deferred via ``transaction.on_commit`` (a no-op under
the test transaction) so these assert the durable DB-row lifecycle — the source
of truth any client reads.
"""

from __future__ import annotations

import uuid

import pytest

from components.shared_platform.infrastructure.services.job_progress import (
    complete_job,
    fail_job,
    start_job,
    update_job,
)
from infrastructure.persistence.core.models import BackgroundJob

pytestmark = [pytest.mark.integration, pytest.mark.django_db]


def test_start_creates_running_job(workspace_factory):
    ws = workspace_factory()
    job_id = start_job(workspace_id=ws.id, job_type="cloud_posture_scan", title="t", phase="scanning", total=375)
    job = BackgroundJob.objects.get(id=job_id)
    assert job.status == BackgroundJob.Status.RUNNING
    assert job.job_type == "cloud_posture_scan"
    assert job.total == 375
    assert job.started_at is not None
    assert job.progress == 0


def test_update_is_monotonic_and_clamped(workspace_factory):
    ws = workspace_factory()
    job_id = start_job(workspace_id=ws.id, job_type="x")
    update_job(job_id=job_id, progress=40, phase="scanning", detail="d")
    update_job(job_id=job_id, progress=10)  # lower — must not regress
    update_job(job_id=job_id, progress=250)  # over 100 — clamp
    job = BackgroundJob.objects.get(id=job_id)
    assert job.progress == 100
    assert job.phase == "scanning"
    assert job.detail == "d"


def test_complete_sets_completed_100(workspace_factory):
    ws = workspace_factory()
    job_id = start_job(workspace_id=ws.id, job_type="x")
    complete_job(job_id=job_id, detail="done", resource_id="abc-123")
    job = BackgroundJob.objects.get(id=job_id)
    assert job.status == BackgroundJob.Status.COMPLETED
    assert job.progress == 100
    assert job.completed_at is not None
    assert job.resource_id == "abc-123"


def test_fail_freezes_progress_and_records_error(workspace_factory):
    ws = workspace_factory()
    job_id = start_job(workspace_id=ws.id, job_type="x")
    update_job(job_id=job_id, progress=30)
    fail_job(job_id=job_id, error="boom")
    job = BackgroundJob.objects.get(id=job_id)
    assert job.status == BackgroundJob.Status.FAILED
    assert job.error == "boom"
    assert job.progress == 30  # frozen where it was, not reset


def test_updates_to_missing_job_are_safe():
    # No such job — best-effort updates must never raise.
    update_job(job_id=str(uuid.uuid4()), progress=50)
    complete_job(job_id=str(uuid.uuid4()))
    fail_job(job_id=str(uuid.uuid4()), error="x")
