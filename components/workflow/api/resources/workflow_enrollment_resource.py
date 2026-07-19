"""Output DTOs for workflow enrollment endpoints."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WorkflowEnrollmentResource:
    """Output DTO for workflow enrollment detail endpoints (GET /api/workflows/<id>/enrollments/<enrollment_id>/)."""
    id: str | None = None
    workflow_id: str | None = None
    target_type: str | None = None
    target_id: str | int | None = None
    status: str | None = None
    enrolled_at: str | None = None
    unenrolled_at: str | None = None


@dataclass(frozen=True)
class WorkflowEnrollmentCollectionResource:
    """Output DTO for workflow enrollment list endpoints (GET /api/workflows/<id>/enrollments/)."""
    items: list[WorkflowEnrollmentResource]
    count: int = 0
    created: int | None = None
