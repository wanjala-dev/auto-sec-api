"""FindingRaised → board Task handler (ADR 0004 Phase 3).

The sole board-surfacing path for cloud-posture findings (the CloudPostureDetector it
replaced was retired). Reproduces that detector's card shape so the card is unchanged.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from components.agents.application.handlers.finding_raised_board_handler import (
    handle_finding_raised_board,
)
from components.findings.domain.entities.finding_entity import FindingEntity
from components.findings.infrastructure.repositories.django_finding_repository import (
    DjangoFindingRepository,
)
from components.shared_kernel.domain.events import FindingRaised
from components.shared_kernel.domain.security import FindingStatus, Severity
from infrastructure.persistence.project.models import Column, Task

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

_NOW = datetime(2026, 7, 25, 12, 0, 0, tzinfo=UTC)


def _seed_finding(ws) -> FindingEntity:
    finding = FindingEntity(
        id=uuid4(),
        workspace_id=ws.id,
        source="cloud_posture.prowler",
        fingerprint="iam_root_mfa_enabled|123456789012|arn:aws:iam::123456789012:root",
        asset_urn="arn:aws:iam::123456789012:root",
        severity=Severity.CRITICAL,
        status=FindingStatus.OPEN,
        title="Root account without MFA",
        first_seen_at=_NOW,
        last_seen_at=_NOW,
        description="The root user has no MFA device.",
        remediation="Enable MFA on the root account.",
        compliance={"CIS-2.0": ["1.5"]},
        attributes={
            "check_id": "iam_root_mfa_enabled",
            "account_id": "123456789012",
            "resource_uid": "arn:aws:iam::123456789012:root",
            "region": "us-east-1",
            "service": "iam",
            "resource_name": "root",
        },
    )
    DjangoFindingRepository().upsert(finding)
    return finding


def _event(finding: FindingEntity, *, source: str = "cloud_posture.prowler") -> FindingRaised:
    return FindingRaised(
        workspace_id=finding.workspace_id,
        finding_id=finding.id,
        fingerprint=finding.fingerprint,
        asset_urn=finding.asset_urn,
        severity=finding.severity.value,
        status=finding.status.value,
        source=source,
        title=finding.title,
        is_new=True,
    )


def test_handler_is_subscribed():
    from components.shared_kernel.application.subscription_registry import SubscriptionRegistry

    assert (FindingRaised, handle_finding_raised_board) in SubscriptionRegistry.entries()


def test_creates_board_task_matching_the_detector_shape(workspace_factory):
    ws = workspace_factory()
    finding = _seed_finding(ws)

    handle_finding_raised_board(_event(finding))

    lookup = "cloud_posture:123456789012:iam_root_mfa_enabled:arn:aws:iam::123456789012:root"
    task = Task.objects.get(
        workspace=ws,
        source_type="ai.cloud_posture",
        metadata__idempotency_key=f"lookup_key:{lookup}",
    )
    assert task.title == "Critical: Root account without MFA"
    assert task.metadata["payload"]["finding_id"] == str(finding.id)  # local copy → its finding
    assert task.metadata["payload"]["check_id"] == "iam_root_mfa_enabled"
    assert task.metadata["payload"]["compliance"] == {"CIS-2.0": ["1.5"]}


def test_card_is_born_in_the_canonical_todo_intake_lane(workspace_factory):
    """ADR 0030 P3 (D2): intake lands in Todo on the AI Findings project
    board — one surface, three consistent FKs, chip ``pending`` from birth."""
    ws = workspace_factory()
    finding = _seed_finding(ws)

    handle_finding_raised_board(_event(finding))

    task = Task.objects.get(workspace=ws, source_type="ai.cloud_posture")
    assert task.column is not None
    assert task.column.title == "Todo"
    assert task.project is not None
    assert task.project.title == "AI Findings"
    assert task.column.project_id == task.project_id
    assert task.column.team_id == task.team_id
    assert task.workflow_status_id == task.column.workflow_status_id
    assert task.workflow_status.name == "Todo"
    assert task.metadata["triage"] == {"status": "pending"}
    # The retired AI vocabulary is never minted for a new workspace.
    assert not Column.objects.filter(
        workspace=ws, title__in=["Suggested", "Under Review", "Accepted", "Dismissed", "Triage", "Optimize"]
    ).exists()


def test_reraise_is_idempotent_no_duplicate_card(workspace_factory):
    ws = workspace_factory()
    finding = _seed_finding(ws)

    handle_finding_raised_board(_event(finding))
    handle_finding_raised_board(_event(finding))  # same lookup_key → no second card

    assert Task.objects.filter(workspace=ws, source_type="ai.cloud_posture").count() == 1


def test_noops_for_unmapped_source(workspace_factory):
    ws = workspace_factory()
    finding = _seed_finding(ws)

    handle_finding_raised_board(_event(finding, source="trivy.cve"))

    assert not Task.objects.filter(workspace=ws, source_type="ai.cloud_posture").exists()
