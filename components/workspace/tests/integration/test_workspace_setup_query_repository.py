"""The security getting-started snapshot runs its 5 EXISTS queries against the
real SSOT models (findings/scans/integrations/membership) — ADR 0007 slice D."""

from __future__ import annotations

import pytest
from django.utils import timezone

from components.workspace.infrastructure.repositories.workspace_setup_query_repository import (
    OrmWorkspaceSetupQueryRepository,
)
from infrastructure.persistence.findings.models import Finding

pytestmark = [pytest.mark.django_db]


class TestWorkspaceSetupQueryRepository:
    def test_fresh_workspace_has_no_milestones(self, workspace_factory):
        workspace = workspace_factory()
        snap = OrmWorkspaceSetupQueryRepository().build_setup_snapshot(workspace)

        assert snap.has_cloud_connected is False
        assert snap.has_first_scan is False
        assert snap.has_findings_triaged is False
        assert snap.has_slack_connected is False
        # workspace_owner alone is not "teammates invited".
        assert snap.has_teammates_invited is False

    def test_any_finding_counts_as_first_scan(self, workspace_factory):
        # Findings only exist because a scan produced them — so even an open
        # finding (no completed ScanRun row) satisfies "run your first scan".
        workspace = workspace_factory()
        now = timezone.now()
        Finding.objects.create(
            workspace=workspace,
            source="cloud_posture.prowler",
            fingerprint="fp-1",
            severity="high",
            status="open",
            first_seen_at=now,
            last_seen_at=now,
        )
        snap = OrmWorkspaceSetupQueryRepository().build_setup_snapshot(workspace)
        assert snap.has_first_scan is True

    def test_triaged_finding_flips_the_milestone(self, workspace_factory):
        workspace = workspace_factory()
        # An open finding does NOT count; a non-open (triaged) one does.
        now = timezone.now()
        Finding.objects.create(
            workspace=workspace,
            source="cloud_posture.prowler",
            fingerprint="fp-open",
            severity="high",
            status="open",
            first_seen_at=now,
            last_seen_at=now,
        )
        snap = OrmWorkspaceSetupQueryRepository().build_setup_snapshot(workspace)
        assert snap.has_findings_triaged is False

        Finding.objects.create(
            workspace=workspace,
            source="cloud_posture.prowler",
            fingerprint="fp-triaged",
            severity="high",
            status="triaged",
            first_seen_at=now,
            last_seen_at=now,
        )
        snap = OrmWorkspaceSetupQueryRepository().build_setup_snapshot(workspace)
        assert snap.has_findings_triaged is True
