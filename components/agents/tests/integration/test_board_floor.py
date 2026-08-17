"""Configurable board floor for ALL AI-board sources (QA report 2026-08-16, §g5).

``min_severity`` used to be hardcoded for code_security / vercel_posture only;
every other source flooded Triage with low-severity cards. The floor is now
resolved per source through ``settings.AI_BOARD_MIN_SEVERITY`` (per-source
override, then the source's baked-in default, then the config's "default"
knob), with defaults preserving current behavior exactly.
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

_NOW = datetime(2026, 8, 16, 12, 0, 0, tzinfo=UTC)
_SOURCE = "cloud_posture.prowler"  # a source with NO baked-in floor


def _seed_finding(ws, severity: Severity) -> FindingEntity:
    finding = FindingEntity(
        id=uuid4(),
        workspace_id=ws.id,
        source=_SOURCE,
        fingerprint=f"check|{uuid4()}",
        asset_urn="arn:aws:iam::123456789012:root",
        severity=severity,
        status=FindingStatus.OPEN,
        title="S3 bucket versioning disabled",
        first_seen_at=_NOW,
        last_seen_at=_NOW,
        description="Versioning is off.",
        remediation="Enable versioning.",
        compliance={},
        attributes={
            "check_id": "s3_bucket_versioning",
            "account_id": "123456789012",
            "resource_uid": f"arn:aws:s3:::bucket-{uuid4()}",
            "region": "us-east-1",
            "service": "s3",
            "resource_name": "bucket",
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
        source=_SOURCE,
        title=finding.title,
        is_new=True,
    )


def _cards(ws):
    return Task.objects.filter(workspace=ws, source_type="ai.cloud_posture")


def test_default_config_preserves_current_behavior(workspace_factory, settings):
    """No config → a source without a baked-in floor still cards LOW findings."""
    settings.AI_BOARD_MIN_SEVERITY = {}
    ws = workspace_factory()

    handle_finding_raised_board(_event(_seed_finding(ws, Severity.LOW)))

    assert _cards(ws).count() == 1


def test_default_knob_floors_every_source(workspace_factory, settings):
    """The "default" key caps the low-severity flood into Triage."""
    settings.AI_BOARD_MIN_SEVERITY = {"default": "high"}
    ws = workspace_factory()

    handle_finding_raised_board(_event(_seed_finding(ws, Severity.LOW)))
    assert _cards(ws).count() == 0, "a below-floor finding stays SSOT-only"

    handle_finding_raised_board(_event(_seed_finding(ws, Severity.CRITICAL)))
    assert _cards(ws).count() == 1, "an above-floor finding still cards"


def test_per_source_override_beats_the_default_knob(workspace_factory, settings):
    settings.AI_BOARD_MIN_SEVERITY = {"default": "high", _SOURCE: "low"}
    ws = workspace_factory()

    handle_finding_raised_board(_event(_seed_finding(ws, Severity.LOW)))

    assert _cards(ws).count() == 1


def test_floor_boundary_is_inclusive(workspace_factory, settings):
    """A finding AT the floor cards; one below it does not."""
    settings.AI_BOARD_MIN_SEVERITY = {_SOURCE: "medium"}
    ws = workspace_factory()

    handle_finding_raised_board(_event(_seed_finding(ws, Severity.MEDIUM)))
    assert _cards(ws).count() == 1

    handle_finding_raised_board(_event(_seed_finding(ws, Severity.LOW)))
    assert _cards(ws).count() == 1
