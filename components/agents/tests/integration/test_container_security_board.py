"""FindingRaised → board Task for Trivy container-image findings (slice 1).

Trivy findings already reach the Finding SSOT (``container_security.trivy``); this pins
that they now also surface on the SOC board via ``_SOURCE_BOARD`` — operator-reading (like
cloud_posture), not yet triaged. Mirrors ``test_finding_raised_board_handler``.
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
from infrastructure.persistence.project.models import Task

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

_NOW = datetime(2026, 7, 26, 12, 0, 0, tzinfo=UTC)


def _seed_trivy_finding(ws) -> FindingEntity:
    finding = FindingEntity(
        id=uuid4(),
        workspace_id=ws.id,
        source="container_security.trivy",
        fingerprint="CVE-2024-1234|registry/app:1.0|openssl|3.0.11",
        asset_urn="urn:oci:registry/app:1.0",
        severity=Severity.HIGH,
        status=FindingStatus.OPEN,
        title="CVE-2024-1234 in openssl",
        first_seen_at=_NOW,
        last_seen_at=_NOW,
        description="A vulnerability in openssl.",
        remediation="Upgrade openssl to 3.0.14",
        attributes={
            "vulnerability_id": "CVE-2024-1234",
            "pkg_name": "openssl",
            "installed_version": "3.0.11",
            "fixed_version": "3.0.14",
            "target": "registry/app:1.0 (debian 12)",
            "primary_url": "https://avd.aquasec.com/nvd/cve-2024-1234",
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


def test_creates_triaged_board_card(workspace_factory):
    ws = workspace_factory()
    finding = _seed_trivy_finding(ws)

    handle_finding_raised_board(_event(finding))

    task = Task.objects.get(workspace=ws, source_type="ai.container_security")
    assert task.title.startswith("High:")
    assert "openssl" in task.title
    # routed to the CVE-triage specialist (slice 2)
    assert task.metadata["agent_type"] == "triage_agent"
    assert task.metadata["payload"]["vulnerability_id"] == "CVE-2024-1234"
    assert task.metadata["payload"]["fixed_version"] == "3.0.14"
    assert task.metadata["payload"]["finding_id"] == str(finding.id)


def test_reraise_is_idempotent_no_duplicate_card(workspace_factory):
    ws = workspace_factory()
    finding = _seed_trivy_finding(ws)
    handle_finding_raised_board(_event(finding))
    handle_finding_raised_board(_event(finding))  # same fingerprint → same lookup_key → no dup
    assert Task.objects.filter(workspace=ws, source_type="ai.container_security").count() == 1
