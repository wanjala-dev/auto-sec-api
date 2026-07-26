"""Slice 1 of logwatch → SSOT: the detector cycle dual-writes ``FindingObserved``.

A logwatch DetectorResult that gets filed on the board (legacy path) ALSO emits a
shared-kernel ``FindingObserved`` so the primary log pillar populates the Finding
SSOT — the mirror of ``prowler_ingest`` for cloud_posture. These pins:

- the emit lands a matching SSOT finding (source / fingerprint / asset_urn / severity),
- severity is derived the SAME way as the board Task (parity, no second threshold),
- the emit is gated to logwatch (a non-logwatch result does NOT double-write — cloud
  posture already emits from prowler_ingest),
- publishing is deferred to commit (nothing lands if the surrounding work rolls back),
- ``FindingRaised`` off this SSOT write does NOT create a duplicate board card for
  logwatch (it is not board-mapped yet).
"""

from __future__ import annotations

import pytest

from components.agents.domain.detectors.base import DetectorResult
from components.agents.infrastructure.adapters.actions.detectors.finding_observed_bridge import (
    emit_finding_observed_for_detector_result,
)
from components.findings.infrastructure.repositories.django_finding_repository import (
    DjangoFindingRepository,
)
from components.shared_kernel.domain.security import Severity
from infrastructure.persistence.workspaces.workflows.models import WorkflowEvent

pytestmark = [pytest.mark.django_db]


def _logwatch_result(*, slug="logwatch.error", service="web", fingerprint="fp-1", impact_score=70):
    return DetectorResult(
        action_type="log_watch" if slug == "logwatch.error" else "log_optimization",
        title=f"[HIGH] {service} · Internal Server Error",
        summary="500s spiking on web — awaiting triage.",
        payload={
            "service": service,
            "signal": "ERROR spike in web",
            "severity": "high",
            "fingerprint": fingerprint,
            "lookup_key": fingerprint,
            "blast_radius": {"service": service, "level": "ERROR", "window_records": 12},
        },
        context={"evidence": [{"type": "log", "detail": "ERROR ..."}], "blast_radius": {}},
        detector_slug=slug,
        agent_type="triage_agent",
        metadata={"impact_score": impact_score},
    )


class TestLogwatchFindingObservedDualWrite:
    def test_emits_matching_ssot_finding(self, workspace_factory, django_capture_on_commit_callbacks):
        ws = workspace_factory()
        result = _logwatch_result(service="web", fingerprint="fp-web-1", impact_score=70)

        with django_capture_on_commit_callbacks(execute=True):
            emit_finding_observed_for_detector_result(ws.id, result)

        finding = DjangoFindingRepository().find_by_identity(ws.id, "logwatch.error", "fp-web-1")
        assert finding is not None
        assert finding.source == "logwatch.error"
        assert finding.severity is Severity.HIGH  # _derive_severity(70) == HIGH — board parity
        assert finding.asset_urn == f"urn:log:{ws.id}/web"
        assert finding.title == result.title
        assert finding.attributes.get("service") == "web"

    def test_critical_score_maps_to_critical_severity(self, workspace_factory, django_capture_on_commit_callbacks):
        ws = workspace_factory()
        with django_capture_on_commit_callbacks(execute=True):
            emit_finding_observed_for_detector_result(ws.id, _logwatch_result(fingerprint="fp-crit", impact_score=90))
        finding = DjangoFindingRepository().find_by_identity(ws.id, "logwatch.error", "fp-crit")
        assert finding is not None
        assert finding.severity is Severity.CRITICAL  # parity with the finding_critical trigger

    def test_optimization_source_is_dual_written(self, workspace_factory, django_capture_on_commit_callbacks):
        ws = workspace_factory()
        with django_capture_on_commit_callbacks(execute=True):
            emit_finding_observed_for_detector_result(
                ws.id, _logwatch_result(slug="logwatch.optimization", fingerprint="fp-opt", impact_score=40)
            )
        finding = DjangoFindingRepository().find_by_identity(ws.id, "logwatch.optimization", "fp-opt")
        assert finding is not None
        assert finding.severity is Severity.MEDIUM

    def test_non_logwatch_result_is_not_dual_written(self, workspace_factory, django_capture_on_commit_callbacks):
        # cloud_posture already emits from prowler_ingest — the cycle bridge must NOT
        # double-write it (or any non-logwatch detector).
        ws = workspace_factory()
        result = _logwatch_result(slug="ai_findings.cloud_posture", fingerprint="fp-cp")
        with django_capture_on_commit_callbacks(execute=True):
            emit_finding_observed_for_detector_result(ws.id, result)
        assert DjangoFindingRepository().find_by_identity(ws.id, "ai_findings.cloud_posture", "fp-cp") is None

    def test_not_published_before_commit(self, workspace_factory, django_capture_on_commit_callbacks):
        ws = workspace_factory()
        # execute=False → on_commit callbacks captured but NOT run → nothing persisted.
        with django_capture_on_commit_callbacks(execute=False):
            emit_finding_observed_for_detector_result(ws.id, _logwatch_result(fingerprint="fp-nocommit"))
        assert DjangoFindingRepository().find_by_identity(ws.id, "logwatch.error", "fp-nocommit") is None

    def test_ssot_write_does_not_create_a_duplicate_board_card(
        self, workspace_factory, django_capture_on_commit_callbacks
    ):
        # FindingRaised off the SSOT write is not board-mapped for logwatch, so the
        # board handler no-ops — no second card, and no finding_* workflow events from
        # this path (those come from the legacy persist_finding_as_task path).
        ws = workspace_factory()
        with django_capture_on_commit_callbacks(execute=True):
            emit_finding_observed_for_detector_result(ws.id, _logwatch_result(fingerprint="fp-nodup"))
        # No workflow finding events were emitted by the SSOT path for this workspace.
        assert not WorkflowEvent.objects.filter(workspace_id=str(ws.id), source_type="finding").exists()
