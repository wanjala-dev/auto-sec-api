"""PostureReportDetector over real finding rows (Phase 1 posture slice).

Real DB; NO LLM anywhere (the detector is deterministic by contract). Pins:
the end-to-end read path (board findings + deep runs → posture aggregates →
ONE evidence-bearing report card), the not-auto-routed contract, the weekly
lookup_key dedupe through ``persist_finding_as_task``, the zero-activity
skip, and that the report never counts itself.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest import mock

import pytest

from components.agents.domain.detectors.base import DetectorContext
from components.agents.infrastructure.adapters.actions.detectors.posture_report import (
    SOURCE_TYPE,
    PostureReportDetector,
)
from infrastructure.persistence.project.models import Column, Task


def _board(workspace_factory, team_factory):
    workspace = workspace_factory()
    owner = workspace.workspace_owner
    team = team_factory(workspace=workspace, created_by=owner, members=[owner])
    column = Column.objects.create(
        team=team, workspace=workspace, project=None, title="Suggested", order=0, created_by=owner
    )
    return workspace, owner, team, column


def _finding(workspace, owner, team, column, i, *, severity="high", triaged=False, needs_human=False):
    metadata = {
        "agent_type": "triage_agent",
        "detector": "logwatch.error",
        "severity": severity,
        "payload": {"signal": f"ERROR {i}", "lookup_key": f"fp-{i}"},
        "provenance": {
            "events": [{"actor": "detector:logwatch.error", "action": "filed finding on the board", "at": "x"}]
        },
    }
    if triaged:
        metadata["triage"] = {
            "status": "triaged",
            "agent": "triage_agent",
            "triaged_at": datetime.now(UTC).isoformat(),
            "needs_human": needs_human,
        }
    return Task.objects.create(
        team=team,
        workspace=workspace,
        column=column,
        created_by=owner,
        title=f"[{severity.upper()}] finding {i}",
        source_type="ai.log_watch",
        metadata=metadata,
    )


def _context(workspace, run_at=None):
    return DetectorContext(
        workspace_id=str(workspace.id),
        teammate_id="teammate-1",
        run_at=run_at or datetime.now(UTC),
        last_run_at=None,
    )


def _persist(result, workspace, column, owner):
    from components.agents.application.handlers.specialist_persistence_service import (
        persist_finding_as_task,
    )

    return persist_finding_as_task(
        workspace=workspace,
        suggested_column=column,
        ai_user_id=str(owner.id),
        title=result.title,
        summary=result.summary,
        source_type=f"ai.{result.action_type}",
        agent_type=result.agent_type or "ai_teammate",
        detector_key=result.detector_slug,
        payload_data=result.payload,
        context=result.context,
        impact_score=int(result.metadata.get("impact_score", 0)),
        idempotency_key=f"lookup_key:{result.payload['lookup_key']}",
    )


@pytest.mark.django_db
class TestPostureReportDetector:
    def test_files_exactly_one_evidence_bearing_report(self, workspace_factory, team_factory):
        workspace, owner, team, column = _board(workspace_factory, team_factory)
        for i in range(3):
            _finding(workspace, owner, team, column, i, severity="high")
        _finding(workspace, owner, team, column, 3, severity="low", triaged=True, needs_human=True)

        results = list(PostureReportDetector().execute(_context(workspace)))

        assert len(results) == 1
        r = results[0]
        assert r.action_type == "posture_report"
        # NOT auto-routed — a posture report is operator reading material.
        assert r.agent_type is None

        payload = r.payload
        assert payload["lookup_key"].startswith("posture_report:")
        assert payload["evidence"], "the aggregated numbers ARE the evidence"
        report = payload["report"]
        assert report["persona"] == "engineer"
        assert report["findings_posture"]["open_findings"]["total"] == 3
        assert report["findings_posture"]["needs_human_backlog"]["count"] == 1
        # Full drill-down: real finding ids ride along as evidence.
        assert len(report["findings_posture"]["open_findings"]["sample_task_ids"]) == 3
        # KPI bands present, medians against the industry yardstick.
        assert report["response_kpis"]["triage_latency_by_severity"]["high"]["band_hours"] == 2.0
        assert set(report["ctem_mapping"]) == {"discovery", "prioritization", "validation", "mobilization"}

    def test_never_calls_an_llm(self, workspace_factory, team_factory):
        workspace, owner, team, column = _board(workspace_factory, team_factory)
        for i in range(2):
            _finding(workspace, owner, team, column, i)

        with (
            mock.patch("components.knowledge.infrastructure.factories.llms.factory.LLMFactory.get_llm") as factory,
            mock.patch("components.knowledge.application.providers.ai_llm_provider.AILlmProvider") as provider,
        ):
            results = list(PostureReportDetector().execute(_context(workspace)))

        assert results  # it did real work…
        factory.assert_not_called()  # …with zero model involvement
        provider.assert_not_called()

    def test_zero_activity_workspace_gets_no_weekly_noise_card(self, workspace_factory, team_factory):
        workspace, _, _, _ = _board(workspace_factory, team_factory)

        assert list(PostureReportDetector().execute(_context(workspace))) == []

    def test_persists_once_per_week_rerun_is_a_noop(self, workspace_factory, team_factory):
        workspace, owner, team, column = _board(workspace_factory, team_factory)
        for i in range(3):
            _finding(workspace, owner, team, column, i)

        run_at = datetime.now(UTC)
        (first,) = PostureReportDetector().execute(_context(workspace, run_at))
        task_id = _persist(first, workspace, column, owner)
        assert task_id is not None

        card = Task.objects.get(id=task_id)
        assert card.source_type == SOURCE_TYPE
        assert card.metadata["payload"]["report"]["findings_posture"]["open_findings"]["total"] >= 3

        # Same week, later cycle → same lookup_key → idempotent no-op.
        (second,) = PostureReportDetector().execute(_context(workspace, run_at + timedelta(days=2)))
        assert second.payload["lookup_key"] == first.payload["lookup_key"]
        assert _persist(second, workspace, column, owner) is None
        assert Task.objects.filter(workspace=workspace, source_type=SOURCE_TYPE).count() == 1

        # Next ISO week → fresh fingerprint → a new report card files.
        (next_week,) = PostureReportDetector().execute(_context(workspace, run_at + timedelta(days=7)))
        assert next_week.payload["lookup_key"] != first.payload["lookup_key"]
        assert _persist(next_week, workspace, column, owner) is not None
        assert Task.objects.filter(workspace=workspace, source_type=SOURCE_TYPE).count() == 2

    def test_report_never_counts_itself(self, workspace_factory, team_factory):
        workspace, owner, team, column = _board(workspace_factory, team_factory)
        for i in range(2):
            _finding(workspace, owner, team, column, i)

        (first,) = PostureReportDetector().execute(_context(workspace))
        _persist(first, workspace, column, owner)

        # Re-aggregate with the report card now on the board: open count is
        # unchanged — ai.posture_report is excluded from every aggregate.
        (again,) = PostureReportDetector().execute(_context(workspace, datetime.now(UTC) + timedelta(days=7)))
        assert again.payload["report"]["findings_posture"]["open_findings"]["total"] == 2
        kinds = again.payload["report"]["findings_posture"]["open_findings"]["by_kind"]
        assert SOURCE_TYPE not in kinds

    def test_router_never_dispatches_the_report(self, workspace_factory, team_factory):
        from components.agents.infrastructure.adapters.actions.detectors.logwatch import (
            AiFindingRouterDetector,
        )

        assert SOURCE_TYPE not in AiFindingRouterDetector.ROUTABLE_SOURCE_TYPES

    def test_registered_in_the_detector_registry(self):
        from components.agents.infrastructure.adapters.actions.detectors import registry

        assert registry.get("posture_report") is PostureReportDetector
        assert PostureReportDetector.cadence == "weekly"

    def test_should_run_self_gates_on_the_cache_lease(self, workspace_factory, team_factory):
        from django.core.cache import cache

        workspace, _, _, _ = _board(workspace_factory, team_factory)
        cache.delete(f"posture_report_detector:lease:{workspace.id}")
        detector = PostureReportDetector()

        assert detector.should_run(_context(workspace)) is True
        # Second cycle inside the lease window is gated (cheap re-run guard;
        # the weekly lookup_key is the correctness guarantee regardless).
        assert detector.should_run(_context(workspace)) is False
        cache.delete(f"posture_report_detector:lease:{workspace.id}")
