"""Reversible logwatch board cutover (ADR 0004) — the FindingRaised → board path.

When ``feature.logwatch_board_from_findings`` is ON for a workspace, a raised logwatch
finding surfaces on the board via the SSOT (finding_raised_board_handler), rebuilding
the EXACT legacy cycle card — same source_type, routing target (agent_type), evidence
payload, and idempotency lookup_key. OFF (default) → the handler no-ops and the cycle
owns the board. cloud_posture stays graduated (flag-less). Also pins the cycle
stand-down helper and the two-sided flag-key consistency.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
from unittest import mock
from uuid import uuid4

import pytest

from components.agents.application.handlers import finding_raised_board_handler as board
from components.agents.application.handlers.finding_raised_board_handler import (
    handle_finding_raised_board,
)
from components.agents.domain.detectors.base import DetectorResult
from components.agents.infrastructure.adapters.actions.detectors import finding_observed_bridge as bridge
from components.findings.domain.entities.finding_entity import FindingEntity
from components.findings.infrastructure.repositories.django_finding_repository import (
    DjangoFindingRepository,
)
from components.shared_kernel.domain.events import FindingRaised
from components.shared_kernel.domain.security import FindingStatus, Severity
from infrastructure.persistence.project.models import Task

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

_NOW = datetime(2026, 7, 25, 12, 0, 0, tzinfo=UTC)


@contextmanager
def _cutover(enabled: bool):
    """Deterministically pin the cutover flag by mocking the provider both call sites
    resolve (board handler + cycle helper) — avoids DB-flag + shared-Redis cache
    nondeterminism (the pattern test_cloud_posture_orchestration uses)."""
    stub = mock.Mock()
    stub.is_feature_enabled.return_value = enabled
    with mock.patch(
        "components.shared_platform.application.providers.feature_flags_provider.get_feature_flags_provider",
        return_value=stub,
    ):
        yield


def _seed_logwatch_finding(
    ws,
    *,
    source="logwatch.error",
    action_type="log_watch",
    agent_type="triage_agent",
    fingerprint="fp-web-500",
    service="web",
    severity=Severity.HIGH,
    impact_score=70,
):
    board_payload = {
        "lookup_key": fingerprint,
        "service": service,
        "signal": "ERROR spike in web",
        "severity": severity.value,
        "message": "500 Internal Server Error x12",
        "evidence": [{"type": "log", "detail": "ERROR ... traceback ..."}],
        "blast_radius": {"service": service, "level": "ERROR", "window_records": 12},
    }
    finding = FindingEntity(
        id=uuid4(),
        workspace_id=ws.id,
        source=source,
        fingerprint=fingerprint,
        asset_urn=f"urn:log:{ws.id}/{service}",
        severity=severity,
        status=FindingStatus.OPEN,
        title=f"[{severity.value.upper()}] {service} · Internal Server Error",
        first_seen_at=_NOW,
        last_seen_at=_NOW,
        description="500s spiking on web — awaiting triage.",
        attributes={
            "service": service,
            "signal": "ERROR spike in web",
            "action_type": action_type,
            "detector_slug": source,
            "agent_type": agent_type,
            "impact_score": impact_score,
            "board_payload": board_payload,
            "board_context": {"evidence": board_payload["evidence"], "blast_radius": board_payload["blast_radius"]},
        },
    )
    DjangoFindingRepository().upsert(finding)
    return finding


def _event(finding, *, source):
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


class TestLogwatchBoardCutover:
    def test_flag_on_creates_a_parity_card_preserving_routing_and_evidence(self, workspace_factory):
        ws = workspace_factory()
        finding = _seed_logwatch_finding(ws, source="logwatch.error", agent_type="triage_agent")

        with _cutover(True):
            handle_finding_raised_board(_event(finding, source="logwatch.error"))

        task = Task.objects.get(workspace=ws, source_type="ai.log_watch")
        # Routing target preserved → the router still dispatches to triage_agent.
        assert task.metadata["agent_type"] == "triage_agent"
        # Full triage evidence preserved (no degradation vs the legacy cycle card).
        assert task.metadata["payload"]["evidence"] == finding.attributes["board_payload"]["evidence"]
        assert task.metadata["payload"]["message"] == "500 Internal Server Error x12"
        assert task.metadata["payload"]["lookup_key"] == finding.fingerprint
        assert task.metadata["payload"]["finding_id"] == str(finding.id)  # local copy → finding
        assert task.metadata["severity"] == "high"

    def test_flag_off_is_a_noop(self, workspace_factory):
        ws = workspace_factory()
        finding = _seed_logwatch_finding(ws, source="logwatch.error")

        with _cutover(False):
            handle_finding_raised_board(_event(finding, source="logwatch.error"))

        assert not Task.objects.filter(workspace=ws, source_type="ai.log_watch").exists()

    def test_optimization_source_routes_to_optimization_agent(self, workspace_factory):
        ws = workspace_factory()
        finding = _seed_logwatch_finding(
            ws,
            source="logwatch.optimization",
            action_type="log_optimization",
            agent_type="optimization_agent",
            fingerprint="fp-opt",
            impact_score=40,
            severity=Severity.MEDIUM,
        )

        with _cutover(True):
            handle_finding_raised_board(_event(finding, source="logwatch.optimization"))

        task = Task.objects.get(workspace=ws, source_type="ai.log_optimization")
        assert task.metadata["agent_type"] == "optimization_agent"

    def test_cutover_is_idempotent(self, workspace_factory):
        ws = workspace_factory()
        finding = _seed_logwatch_finding(ws)
        ev = _event(finding, source="logwatch.error")

        with _cutover(True):
            handle_finding_raised_board(ev)
            handle_finding_raised_board(ev)  # re-raise → same lookup_key → no duplicate card

        assert Task.objects.filter(workspace=ws, source_type="ai.log_watch").count() == 1

    def test_cloud_posture_still_surfaces_without_a_flag(self, workspace_factory):
        # Regression: the refactor must not break the graduated (flag-less) pillar.
        ws = workspace_factory()
        finding = FindingEntity(
            id=uuid4(),
            workspace_id=ws.id,
            source="cloud_posture.prowler",
            fingerprint="chk|acct|arn",
            asset_urn="arn:aws:iam::1:root",
            severity=Severity.CRITICAL,
            status=FindingStatus.OPEN,
            title="Root no MFA",
            first_seen_at=_NOW,
            last_seen_at=_NOW,
            remediation="Enable MFA.",
            attributes={"check_id": "chk", "account_id": "acct", "resource_uid": "arn"},
        )
        DjangoFindingRepository().upsert(finding)

        handle_finding_raised_board(_event(finding, source="cloud_posture.prowler"))

        assert Task.objects.filter(workspace=ws, source_type="ai.cloud_posture").exists()


class TestCycleStandDownHelper:
    def _result(self, slug="logwatch.error"):
        return DetectorResult(
            action_type="log_watch",
            title="t",
            summary="s",
            payload={"lookup_key": "fp", "service": "web"},
            context={},
            detector_slug=slug,
            agent_type="triage_agent",
            metadata={"impact_score": 70},
        )

    def test_active_only_for_logwatch_when_flag_on(self, workspace_factory):
        ws = workspace_factory()
        with _cutover(True):
            assert bridge.logwatch_board_cutover_active(ws.id, self._result("logwatch.error")) is True
            # Non-logwatch is never stood down by this cutover, even with the flag on
            # (the gate short-circuits on detector_slug before checking the flag).
            assert bridge.logwatch_board_cutover_active(ws.id, self._result("ai_findings.cloud_posture")) is False

    def test_inactive_when_flag_off(self, workspace_factory):
        ws = workspace_factory()
        with _cutover(False):
            assert bridge.logwatch_board_cutover_active(ws.id, self._result("logwatch.error")) is False


def test_flag_key_is_consistent_across_handler_and_bridge():
    # The cycle stand-down and the board handler MUST gate the same key, or a workspace
    # could stand down the cycle write while the handler declines to surface the card.
    assert board._LOGWATCH_CUTOVER_FLAG == bridge.LOGWATCH_BOARD_CUTOVER_FLAG


def test_bridge_carries_full_evidence_for_the_cutover():
    # The FindingObserved the bridge emits must carry everything the cutover card needs.
    from uuid import uuid4 as _uuid4

    result = DetectorResult(
        action_type="log_watch",
        title="[HIGH] web",
        summary="s",
        payload={"lookup_key": "fp1", "service": "web", "signal": "ERR", "evidence": [{"d": 1}]},
        context={"evidence": [{"d": 1}], "blast_radius": {"x": 1}},
        detector_slug="logwatch.error",
        agent_type="triage_agent",
        metadata={"impact_score": 70},
    )
    event = bridge._build_finding_observed(_uuid4(), result)
    attrs = event.attributes
    assert attrs["agent_type"] == "triage_agent"
    assert attrs["impact_score"] == 70
    assert attrs["board_payload"]["evidence"] == [{"d": 1}]
    assert attrs["board_context"]["blast_radius"] == {"x": 1}
