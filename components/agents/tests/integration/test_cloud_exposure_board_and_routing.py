"""ADR 0005 phase 3 — cloud attack-path findings become triaged board cards.

A ``cloud_graph.attack_path`` FindingRaised must surface a board Task with
``source_type="ai.cloud_exposure"`` routed to the ``triage_agent`` (via
``metadata.agent_type``), and the router must own that source_type. Mirrors the
cloud_posture board test, but asserts the TRIAGE routing cloud_posture deliberately lacks.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from components.agents.application.handlers.finding_raised_board_handler import (
    handle_finding_raised_board,
)
from components.agents.infrastructure.adapters.actions.detectors.logwatch import (
    AiFindingRouterDetector,
)
from components.findings.domain.entities.finding_entity import FindingEntity
from components.findings.infrastructure.repositories.django_finding_repository import (
    DjangoFindingRepository,
)
from components.shared_kernel.domain.events import FindingRaised
from components.shared_kernel.domain.security import FindingStatus, Severity
from infrastructure.persistence.project.models import Task

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

_NOW = datetime(2026, 7, 26, 12, 0, 0, tzinfo=UTC)


def _seed_attack_path_finding(ws) -> FindingEntity:
    finding = FindingEntity(
        id=uuid4(),
        workspace_id=ws.id,
        source="cloud_graph.attack_path",
        fingerprint="attack_path:11111111-1111-5111-8111-111111111111",
        asset_urn="urn:aws_ec2_instance:arn:ec2:web",  # the entry foothold
        severity=Severity.CRITICAL,
        status=FindingStatus.OPEN,
        title="Public aws_ec2_instance 'web-frontend' can reach AdministratorAccess",
        first_seen_at=_NOW,
        last_seen_at=_NOW,
        description="web-frontend (public aws_ec2_instance) -[can_assume]-> app-exec-role -[has_policy]-> AdministratorAccess",
        remediation="Break the chain: remove the public exposure or strip the admin policy.",
        attributes={
            "agent_type": "triage_agent",
            "impact_score": 95,
            "category": "public_compute_admin",
            "category_label": "Public compute with admin privileges",
            "risk_score": 95.0,
            "length": 2,
            "entry_label": "web-frontend",
            "entry_asset_urn": "urn:aws_ec2_instance:arn:ec2:web",
            "target_label": "AdministratorAccess",
            "target_asset_urn": "urn:aws_iam_policy:arn:iam:admin",
            "asset_urns": ["urn:aws_ec2_instance:arn:ec2:web", "urn:x", "urn:aws_iam_policy:arn:iam:admin"],
            "legs": [
                {"src_label": "web-frontend", "relation": "can_assume", "dst_label": "app-exec-role"},
                {"src_label": "app-exec-role", "relation": "has_policy", "dst_label": "AdministratorAccess"},
            ],
        },
    )
    DjangoFindingRepository().upsert(finding)
    return finding


def _event(finding: FindingEntity) -> FindingRaised:
    return FindingRaised(
        workspace_id=finding.workspace_id,
        finding_id=finding.id,
        fingerprint=finding.fingerprint,
        asset_urn=finding.asset_urn,
        severity=finding.severity.value,
        status=finding.status.value,
        source=finding.source,
        title=finding.title,
        is_new=True,
    )


def test_router_owns_cloud_exposure_source_type():
    assert "ai.cloud_exposure" in AiFindingRouterDetector.ROUTABLE_SOURCE_TYPES


def test_creates_triaged_board_card(workspace_factory):
    ws = workspace_factory()
    finding = _seed_attack_path_finding(ws)

    handle_finding_raised_board(_event(finding))

    task = Task.objects.get(workspace=ws, source_type="ai.cloud_exposure")
    # routed to the generic triager (cloud_posture stays "ai_teammate" = un-triaged)
    assert task.metadata["agent_type"] == "triage_agent"
    assert task.metadata["agent_type"] not in AiFindingRouterDetector._NON_SPECIALIST
    assert task.title.startswith("Critical:")
    assert task.metadata["payload"]["finding_id"] == str(finding.id)
    assert task.metadata["payload"]["category"] == "public_compute_admin"
    # the path legs are carried as evidence
    assert any("can_assume" in line for line in task.metadata["payload"]["evidence"])


def test_reraise_is_idempotent_no_duplicate_card(workspace_factory):
    ws = workspace_factory()
    finding = _seed_attack_path_finding(ws)
    handle_finding_raised_board(_event(finding))
    handle_finding_raised_board(_event(finding))  # same fingerprint → same lookup_key → no dup
    assert Task.objects.filter(workspace=ws, source_type="ai.cloud_exposure").count() == 1
