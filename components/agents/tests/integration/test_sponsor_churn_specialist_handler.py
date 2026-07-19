"""Integration test: SponsorChurnRiskFindingsDetected → Task.

Phase 5b of the Agents-as-Teammates migration. Post-Phase-5
(``AIAction`` retired): each finding lands as a Kanban Task carrying
narrative on ``Task.description`` and detector context on
``Task.metadata``.
"""
from __future__ import annotations

from uuid import UUID

import pytest

from components.agents.application.handlers.sponsor_churn_specialist_handler import (
    handle_sponsor_churn_risk_findings_detected,
)
from components.sponsorship.domain.events.sponsor_churn_risk_findings_detected_event import (
    SponsorChurnRiskFindingsDetected,
)


def _build_event(*, workspace_id: UUID, findings=None) -> SponsorChurnRiskFindingsDetected:
    if findings is None:
        findings = (
            {
                "donor_email": "ada@example.com",
                "donor_name": "Ada Lovelace",
                "donation_count": 12,
                "last_donation_date": "2026-01-01",
                "days_silent": 140,
                "median_interval_days": 30,
                "total_given": "800.00",
                "impact_score": 60,
            },
            {
                "donor_email": "ben@example.com",
                "donor_name": "Ben",
                "donation_count": 3,
                "last_donation_date": "2026-03-15",
                "days_silent": 60,
                "median_interval_days": 20,
                "total_given": "150.00",
                "impact_score": 40,
            },
        )
    return SponsorChurnRiskFindingsDetected(
        workspace_id=workspace_id,
        detector_key="sponsor_churn_interval",
        findings=findings,
    )


@pytest.mark.django_db
class TestSponsorChurnSpecialistHandler:
    def test_creates_task_per_finding(self, workspace_factory):
        from infrastructure.persistence.project.models import Task

        workspace = workspace_factory()
        event = _build_event(workspace_id=workspace.id)

        handle_sponsor_churn_risk_findings_detected(event)

        tasks = list(
            Task.objects.filter(
                workspace=workspace, source_type="ai.sponsor_churn_risk"
            ).order_by("metadata__context__donor_email")
        )
        assert len(tasks) == 2
        for task in tasks:
            assert task.metadata["action_type"] == "sponsor_churn_risk"
            assert task.metadata["agent_type"] == "sponsorship_specialist"
            assert task.metadata["detector"] == "sponsor_churn_interval"
            assert task.workspace_id == workspace.id

    def test_idempotent_on_donor_last_donation_date_dedup(self, workspace_factory):
        from infrastructure.persistence.project.models import Task

        workspace = workspace_factory()
        event = _build_event(workspace_id=workspace.id)

        handle_sponsor_churn_risk_findings_detected(event)
        handle_sponsor_churn_risk_findings_detected(event)

        assert (
            Task.objects.filter(
                workspace=workspace, source_type="ai.sponsor_churn_risk"
            ).count()
            == 2
        )

    def test_handles_workspace_missing_gracefully(self):
        from uuid import uuid4

        event = _build_event(workspace_id=uuid4())
        handle_sponsor_churn_risk_findings_detected(event)
