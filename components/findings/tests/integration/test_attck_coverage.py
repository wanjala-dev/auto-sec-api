"""Recompute → materialize → read the ATT&CK coverage heatmap, over the real repo."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from components.findings.application.use_cases.get_attck_coverage_use_case import (
    GetAttckCoverageUseCase,
)
from components.findings.application.use_cases.recompute_attck_coverage_use_case import (
    RecomputeAttckCoverageUseCase,
)
from components.findings.infrastructure.repositories.attck_coverage_repository import (
    DjangoAttckCoverageRepository,
)

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

_NOW = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)


def _finding(ws, *, fingerprint, severity, compliance, status="open"):
    from infrastructure.persistence.findings.models import Finding

    return Finding.objects.create(
        workspace=ws,
        source="cloud_graph.attack_path",
        fingerprint=fingerprint,
        asset_urn=f"urn:{fingerprint}",
        severity=severity,
        status=status,
        title=f"finding {fingerprint}",
        compliance=compliance,
        first_seen_at=_NOW,
        last_seen_at=_NOW,
    )


def _repo():
    return DjangoAttckCoverageRepository()


class TestRecompute:
    def test_materializes_heatmap_from_open_tagged_findings(self, workspace_factory):
        ws = workspace_factory()
        _finding(ws, fingerprint="a", severity="critical", compliance={"MITRE ATT&CK": ["T1190", "T1078.004"]})
        _finding(ws, fingerprint="b", severity="high", compliance={"MITRE ATT&CK": ["T1190"]})
        # excluded: resolved finding, and a finding with no ATT&CK tag
        _finding(ws, fingerprint="c", severity="high", compliance={"MITRE ATT&CK": ["T1530"]}, status="resolved")
        _finding(ws, fingerprint="d", severity="high", compliance={"CIS-2.0": ["1.1"]})

        cov = RecomputeAttckCoverageUseCase(store=_repo()).execute(ws.id, _NOW)

        assert cov["totals"] == {"techniques": 2, "findings": 2, "tactics": 2}
        ia = next(t for t in cov["tactics"] if t["tactic"] == "initial_access")
        t1190 = ia["techniques"][0]
        assert t1190["technique_id"] == "T1190"
        assert t1190["finding_count"] == 2  # findings a + b
        assert t1190["max_severity"] == "critical"

    def test_persists_a_single_row_overwritten_on_recompute(self, workspace_factory):
        ws = workspace_factory()
        _finding(ws, fingerprint="a", severity="high", compliance={"MITRE ATT&CK": ["T1190"]})
        repo = _repo()
        RecomputeAttckCoverageUseCase(store=repo).execute(ws.id, _NOW)
        RecomputeAttckCoverageUseCase(store=repo).execute(ws.id, _NOW)  # idempotent

        from infrastructure.persistence.findings.models import WorkspaceAttckCoverage

        assert WorkspaceAttckCoverage.objects.filter(workspace=ws).count() == 1
        snap = repo.get(ws.id)
        assert snap.technique_count == 1 and snap.finding_count == 1


class TestRead:
    def test_unmaterialized_is_stale(self, workspace_factory):
        ws = workspace_factory()
        snap, is_stale = GetAttckCoverageUseCase(store=_repo()).execute(ws.id, _NOW)
        assert not snap.is_materialized
        assert is_stale is True

    def test_fresh_materialization_not_stale(self, workspace_factory):
        ws = workspace_factory()
        _finding(ws, fingerprint="a", severity="high", compliance={"MITRE ATT&CK": ["T1190"]})
        repo = _repo()
        RecomputeAttckCoverageUseCase(store=repo).execute(ws.id, _NOW)

        snap, is_stale = GetAttckCoverageUseCase(store=repo).execute(ws.id, _NOW, ttl_seconds=300)
        assert snap.is_materialized and is_stale is False

    def test_aged_materialization_is_stale(self, workspace_factory):
        ws = workspace_factory()
        _finding(ws, fingerprint="a", severity="high", compliance={"MITRE ATT&CK": ["T1190"]})
        repo = _repo()
        RecomputeAttckCoverageUseCase(store=repo).execute(ws.id, _NOW)

        later = _NOW + timedelta(seconds=301)
        _, is_stale = GetAttckCoverageUseCase(store=repo).execute(ws.id, later, ttl_seconds=300)
        assert is_stale is True

    def test_workspace_isolation(self, workspace_factory):
        ws_a = workspace_factory()
        ws_b = workspace_factory()
        _finding(ws_a, fingerprint="a", severity="high", compliance={"MITRE ATT&CK": ["T1190"]})
        repo = _repo()
        RecomputeAttckCoverageUseCase(store=repo).execute(ws_a.id, _NOW)
        assert not repo.get(ws_b.id).is_materialized
