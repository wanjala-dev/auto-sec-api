"""Read queries for ``BackgroundJob`` — power the jobs read API.

Keeps ORM access out of the controller (which stays thin/ORM-free). Serves the
active-jobs list (the HUD polls this to render live progress rings) and a single
job snapshot (initial load / reconnect for a per-resource WS subscription).
"""

from __future__ import annotations


def _serialize(job) -> dict:
    return {
        "id": str(job.id),
        "job_type": job.job_type,
        "title": job.title,
        "status": job.status,
        "phase": job.phase,
        "detail": job.detail,
        "progress": int(job.progress or 0),
        "total": job.total,
        "completed": job.completed,
        "resource_id": job.resource_id,
        "error": job.error,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        "created_at": job.created_at.isoformat() if job.created_at else None,
    }


def list_active_jobs(*, workspace_id, job_type: str | None = None, limit: int = 20) -> list[dict]:
    """Running jobs for a workspace (optionally one job_type), newest first."""
    from infrastructure.persistence.core.models import BackgroundJob

    qs = BackgroundJob.objects.filter(workspace_id=workspace_id, status=BackgroundJob.Status.RUNNING)
    if job_type:
        qs = qs.filter(job_type=job_type)
    return [_serialize(j) for j in qs.order_by("-created_at")[:limit]]


def get_job_for_workspace(*, workspace_id, job_id) -> dict | None:
    """A single job snapshot, scoped to the workspace (auth boundary)."""
    from infrastructure.persistence.core.models import BackgroundJob

    job = BackgroundJob.objects.filter(id=job_id, workspace_id=workspace_id).first()
    return _serialize(job) if job else None


def is_workspace_member(*, user, workspace_id) -> bool:
    """True if the user may read this workspace's jobs (member/staff/superuser)."""
    if getattr(user, "is_staff", False) or getattr(user, "is_superuser", False):
        return True
    from infrastructure.persistence.workspaces.models import WorkspaceMembership

    return WorkspaceMembership.objects.filter(
        workspace_id=workspace_id, user=user, status="active"
    ).exists()
