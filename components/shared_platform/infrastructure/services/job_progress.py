"""Report progress of a long-running job to the user — the canonical seam.

Any Celery task we want to surface live to a user (CSPM scan today; OSINT /
recon / enumeration runs and report generation next) drives a ``BackgroundJob``
through this reporter. Each call persists the lifecycle + progress to the row
AND pushes a realtime event over the shared resource stream (``resource_type``
``BackgroundJob.RESOURCE_TYPE``), so ONE generic frontend renders every job type
with no per-feature UI work.

Usage::

    job_id = start_job(workspace_id=ws, job_type="cloud_posture_scan",
                       title="CSPM scan · 123", phase="scanning")
    update_job(job_id=job_id, progress=42, phase="scanning", detail="…")
    complete_job(job_id=job_id, detail="150 findings")
    # or fail_job(job_id=job_id, error="…")

Callers throttle their OWN cadence (write on ≥1% change or every few seconds).
Each function here is one row write + one realtime publish; the publish is
deferred to ``transaction.on_commit`` so a subscriber never sees an event before
the row is committed (in a bare Celery task with no open transaction that fires
immediately). Progress is clamped monotonic in ``[0, 100]``.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)


def start_job(
    *,
    workspace_id,
    job_type: str,
    title: str = "",
    resource_id: str = "",
    total: int | None = None,
    phase: str = "",
    detail: str = "",
) -> str:
    """Create a RUNNING job row, publish a ``started`` event, return its id."""
    from infrastructure.persistence.core.models import BackgroundJob

    job = BackgroundJob.objects.create(
        workspace_id=workspace_id,
        job_type=job_type,
        title=title,
        resource_id=str(resource_id or ""),
        total=total,
        phase=phase,
        detail=detail,
        status=BackgroundJob.Status.RUNNING,
        progress=0,
        started_at=timezone.now(),
    )
    logger.info("job_started job_id=%s job_type=%s ws=%s", job.id, job_type, workspace_id)
    _publish(job, event_name="started")
    return str(job.id)


def update_job(
    *,
    job_id: str,
    progress: int | None = None,
    phase: str | None = None,
    detail: str | None = None,
    completed: int | None = None,
    resource_id: str | None = None,
) -> None:
    """Update progress/phase/detail on a running job and publish a ``progress`` event."""
    from infrastructure.persistence.core.models import BackgroundJob

    job = BackgroundJob.objects.filter(id=job_id).first()
    if job is None:
        return
    fields: list[str] = []
    if progress is not None:
        job.progress = max(int(job.progress or 0), min(int(progress), 100))  # monotonic, clamped
        fields.append("progress")
    if phase is not None:
        job.phase = phase
        fields.append("phase")
    if detail is not None:
        job.detail = detail
        fields.append("detail")
    if completed is not None:
        job.completed = completed
        fields.append("completed")
    if resource_id is not None:
        job.resource_id = str(resource_id)
        fields.append("resource_id")
    if fields:
        fields.append("updated_at")
        job.save(update_fields=fields)
    _publish(job, event_name="progress")


def complete_job(*, job_id: str, detail: str = "", resource_id: str | None = None) -> None:
    """Mark a job COMPLETED at 100% and publish a ``completed`` event."""
    _finish(job_id, status="completed", progress=100, detail=detail, resource_id=resource_id)


def fail_job(*, job_id: str, error: str = "") -> None:
    """Mark a job FAILED (progress frozen where it was) and publish a ``failed`` event."""
    _finish(job_id, status="failed", error=str(error)[:2000])


def _finish(job_id, *, status, progress=None, detail="", error="", resource_id=None) -> None:
    from infrastructure.persistence.core.models import BackgroundJob

    job = BackgroundJob.objects.filter(id=job_id).first()
    if job is None:
        return
    job.status = status
    job.completed_at = timezone.now()
    fields = ["status", "completed_at", "updated_at"]
    if progress is not None:
        job.progress = progress
        fields.append("progress")
    if detail:
        job.detail = detail
        fields.append("detail")
    if error:
        job.error = error
        fields.append("error")
    if resource_id is not None:
        job.resource_id = str(resource_id)
        fields.append("resource_id")
    job.save(update_fields=fields)
    logger.info("job_%s job_id=%s progress=%s", status, job.id, job.progress)
    _publish(job, event_name=status)


def _publish(job, *, event_name: str) -> None:
    from components.shared_platform.application.providers.realtime_event_provider import (
        get_realtime_event_publisher,
    )
    from infrastructure.persistence.core.models import BackgroundJob

    publisher = get_realtime_event_publisher(enabled=getattr(settings, "REALTIME_EVENTS_ENABLED", True))

    workspace_id = str(job.workspace_id)
    resource_id = str(job.id)
    payload = {
        "job_type": job.job_type,
        "title": job.title,
        "phase": job.phase,
        "detail": job.detail,
        "resource_id": job.resource_id,
        "total": job.total,
        "completed": job.completed,
        "error": job.error,
    }
    status = job.status
    progress = int(job.progress or 0)

    def _do() -> None:
        try:
            publisher.publish(
                workspace_id=workspace_id,
                resource_type=BackgroundJob.RESOURCE_TYPE,
                resource_id=resource_id,
                event_name=event_name,
                status=status,
                progress_percent=progress,
                payload=payload,
            )
        except Exception:  # noqa: BLE001 — a publish failure must never break the job
            logger.exception("job_progress_publish_failed job_id=%s", resource_id)

    transaction.on_commit(_do)
