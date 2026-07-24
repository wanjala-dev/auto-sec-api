"""Integration tests for the ProvenanceLeastPrivilegeDetector.

Verifies the detector both refreshes the graph (backfill) and emits
least-privilege findings for unused grants — the two jobs #17 + #18.
"""

from __future__ import annotations

import pytest
from django.utils import timezone

from components.agents.domain.detectors.base import DetectorContext
from components.agents.infrastructure.adapters.actions.detectors.provenance import (
    ProvenanceLeastPrivilegeDetector,
)
from infrastructure.persistence.provenance.models import AccessGrant
from infrastructure.persistence.workspaces.models import WorkspaceMembership

pytestmark = [pytest.mark.integration, pytest.mark.django_db]


def _ctx(ws):
    return DetectorContext(workspace_id=str(ws.id), teammate_id="t", run_at=timezone.now(), last_run_at=None)


def test_detector_refreshes_graph_and_flags_unused_admin_grant(workspace_factory, user_factory):
    ws = workspace_factory()
    member = user_factory()
    WorkspaceMembership.objects.create(workspace=ws, user=member, role="admin")

    results = list(ProvenanceLeastPrivilegeDetector().execute(_ctx(ws)))

    # (#17) the graph was refreshed from the membership source.
    assert AccessGrant.objects.filter(workspace=ws).exists()

    # (#18) the unused admin grant surfaced as a finding.
    assert any(r.action_type == "provenance_least_privilege" for r in results)
    admin_result = next(r for r in results if r.metadata.get("impact_score") == 60)
    assert admin_result.agent_type is None
    assert admin_result.payload["lookup_key"].startswith("provenance_least_privilege:")
    assert "admin" in admin_result.payload["permissions"]
    assert admin_result.payload["unused_days"] == 30


def test_detector_should_run_leases_to_hourly(workspace_factory):
    ws = workspace_factory()
    detector = ProvenanceLeastPrivilegeDetector()
    ctx = _ctx(ws)

    assert detector.should_run(ctx) is True
    # Same workspace within the lease window — suppressed.
    assert detector.should_run(ctx) is False
