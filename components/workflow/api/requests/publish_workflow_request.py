"""Input DTO for workflow publishing."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PublishWorkflowRequest:
    """Input DTO for POST /api/workflows/<id>/publish endpoint (WorkflowViewSet.publish).

    Used to publish a workflow and create a new version.
    """
    workflow_id: str | int
    notes: str | None = None
