"""Sample-data seed/clear (onboarding slice B): seeds a realistic set, is guarded
off workspaces with real findings, clears only sample rows, and never fires events."""

from __future__ import annotations

import pytest
from django.utils import timezone

from components.findings.application.providers.finding_provider import FindingProvider
from components.findings.infrastructure.sample_findings import SAMPLE_FINDINGS
from components.shared_kernel.domain.security import SAMPLE_SOURCE_PREFIX
from infrastructure.persistence.findings.models import Finding

pytestmark = [pytest.mark.django_db]


def _sample_count(workspace):
    return Finding.objects.filter(workspace=workspace, source__startswith=SAMPLE_SOURCE_PREFIX).count()


class TestSampleData:
    def test_seed_creates_the_sample_set(self, workspace_factory):
        workspace = workspace_factory()
        result = FindingProvider.build_seed_sample_data_use_case().execute(workspace.id, now=timezone.now())

        assert result == {"seeded": len(SAMPLE_FINDINGS), "skipped": False}
        assert _sample_count(workspace) == len(SAMPLE_FINDINGS)
        # every seeded row is sample-sourced + flagged.
        for f in Finding.objects.filter(workspace=workspace):
            assert f.source.startswith(SAMPLE_SOURCE_PREFIX)
            assert f.attributes.get("sample") is True

    def test_seed_is_guarded_off_a_workspace_with_real_findings(self, workspace_factory):
        workspace = workspace_factory()
        now = timezone.now()
        Finding.objects.create(
            workspace=workspace,
            source="cloud_posture.prowler",  # a REAL finding
            fingerprint="real-1",
            severity="high",
            status="open",
            first_seen_at=now,
            last_seen_at=now,
        )
        result = FindingProvider.build_seed_sample_data_use_case().execute(workspace.id, now=now)

        assert result == {"seeded": 0, "skipped": True}
        assert _sample_count(workspace) == 0

    def test_clear_removes_only_sample_rows(self, workspace_factory):
        workspace = workspace_factory()
        now = timezone.now()
        FindingProvider.build_seed_sample_data_use_case().execute(workspace.id, now=now)
        # a real finding lands after sampling (edge case) — must survive the clear.
        Finding.objects.create(
            workspace=workspace,
            source="cloud_posture.prowler",
            fingerprint="real-1",
            severity="high",
            status="open",
            first_seen_at=now,
            last_seen_at=now,
        )

        result = FindingProvider.build_clear_sample_data_use_case().execute(workspace.id, now=now)

        assert result == {"deleted": len(SAMPLE_FINDINGS)}
        assert _sample_count(workspace) == 0
        assert Finding.objects.filter(workspace=workspace).count() == 1  # the real one remains
