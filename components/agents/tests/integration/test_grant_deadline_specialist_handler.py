"""Integration test: GrantDeadlineUpcomingFindingsDetected → Task.

Phase 5b of the Agents-as-Teammates migration — closes out the detector
migrations. Post-Phase-5: ``AIAction`` is gone; everything writes a
Kanban Task carrying narrative on ``Task.description`` and detector
context on ``Task.metadata``.
"""
from __future__ import annotations

from uuid import UUID

import pytest

from components.agents.application.handlers.grant_deadline_specialist_handler import (
    handle_grant_deadline_upcoming_findings_detected,
)
from components.grants.domain.events.grant_deadline_upcoming_findings_detected_event import (
    GrantDeadlineUpcomingFindingsDetected,
)


def _build_event(*, workspace_id: UUID, findings=None) -> GrantDeadlineUpcomingFindingsDetected:
    if findings is None:
        findings = (
            {
                "grant_id": "g-1",
                "grant_title": "Capacity Building",
                "funder_name": "Acme Foundation",
                "submission_deadline": "2026-06-30",
                "days_remaining": 14,
                "amount_requested": "50000",
                "impact_score": 55,
            },
            {
                "grant_id": "g-2",
                "grant_title": "Programs",
                "funder_name": "",
                "submission_deadline": "2026-06-07",
                "days_remaining": 2,
                "amount_requested": "10000",
                "impact_score": 95,
            },
        )
    return GrantDeadlineUpcomingFindingsDetected(
        workspace_id=workspace_id,
        detector_key="grant_deadline_upcoming",
        findings=findings,
    )


@pytest.mark.django_db
class TestGrantDeadlineSpecialistHandler:
    def test_creates_task_per_finding(self, workspace_factory):
        from infrastructure.persistence.project.models import Task

        workspace = workspace_factory()
        event = _build_event(workspace_id=workspace.id)

        handle_grant_deadline_upcoming_findings_detected(event)

        tasks = list(
            Task.objects.filter(
                workspace=workspace,
                source_type="ai.grant_deadline_upcoming",
            ).order_by("metadata__context__grant_id")
        )
        assert len(tasks) == 2
        for task in tasks:
            assert task.metadata["action_type"] == "grant_deadline_upcoming"
            assert task.metadata["agent_type"] == "grants_specialist"
            assert task.metadata["detector"] == "grant_deadline_upcoming"
            assert task.workspace_id == workspace.id

    def test_idempotent_on_grant_deadline_dedup(self, workspace_factory):
        from infrastructure.persistence.project.models import Task

        workspace = workspace_factory()
        event = _build_event(workspace_id=workspace.id)

        handle_grant_deadline_upcoming_findings_detected(event)
        handle_grant_deadline_upcoming_findings_detected(event)

        assert (
            Task.objects.filter(
                workspace=workspace,
                source_type="ai.grant_deadline_upcoming",
            ).count()
            == 2
        )

    def test_handles_workspace_missing_gracefully(self):
        from uuid import uuid4

        event = _build_event(workspace_id=uuid4())
        handle_grant_deadline_upcoming_findings_detected(event)
