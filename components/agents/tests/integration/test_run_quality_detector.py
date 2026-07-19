"""AgentRunQualityDetector over real finding rows (task #46).

Real DB; NO LLM anywhere (the detector is deterministic by contract — one test
pins that a reachable LLM provider is never touched). Pins the end-to-end
read path: triage outcomes + ``run_telemetry`` stamps → windowed aggregation →
an evidence-bearing ``DetectorResult`` that is NOT auto-routed, plus the
board persistence round-trip through ``persist_finding_as_task``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest import mock

import pytest

from components.agents.domain.detectors.base import DetectorContext
from components.agents.infrastructure.adapters.actions.detectors.run_quality import (
    METRIC_NEEDS_HUMAN,
    SOURCE_TYPE,
    AgentRunQualityDetector,
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


def _handled_finding(workspace, owner, team, column, i, *, agent="triage_agent", needs_human=False, telemetry=None):
    metadata = {
        "agent_type": agent,
        "detector": "logwatch.error",
        "triage": {
            "status": "triaged",
            "agent": agent,
            "triaged_at": datetime.now(UTC).isoformat(),
            "needs_human": needs_human,
        },
        "payload": {"signal": f"ERROR {i}", "lookup_key": f"fp-{i}"},
    }
    if telemetry is not None:
        metadata["run_telemetry"] = telemetry
    return Task.objects.create(
        team=team,
        workspace=workspace,
        column=column,
        created_by=owner,
        title=f"[HIGH] finding {i}",
        source_type="ai.log_watch",
        metadata=metadata,
    )


def _context(workspace):
    return DetectorContext(
        workspace_id=str(workspace.id),
        teammate_id="teammate-1",
        run_at=datetime.now(UTC),
        last_run_at=None,
    )


@pytest.mark.django_db
class TestRunQualityDetector:
    def test_sustained_needs_human_breach_files_evidence_bearing_finding(self, workspace_factory, team_factory):
        workspace, owner, team, column = _board(workspace_factory, team_factory)
        for i in range(6):
            _handled_finding(workspace, owner, team, column, i, needs_human=(i < 4))

        results = list(AgentRunQualityDetector().execute(_context(workspace)))

        assert len(results) == 1
        r = results[0]
        assert r.action_type == "agent_run_quality"
        # NOT auto-routed — a human owns the intervention.
        assert r.agent_type is None
        payload = r.payload
        assert payload["agent_under_review"] == "triage_agent"
        assert payload["metric"] == METRIC_NEEDS_HUMAN
        assert payload["numerator"] == 4 and payload["denominator"] == 6
        assert payload["threshold"] == 0.5
        assert len(payload["sample_task_ids"]) == 4
        assert payload["evidence"], "the aggregated numbers ARE the evidence"
        assert payload["lookup_key"].startswith("agent_run_quality:triage_agent:needs_human_rate:")
        assert r.context["blast_radius"]["findings_in_window"] == 6

    def test_blip_files_nothing(self, workspace_factory, team_factory):
        workspace, owner, team, column = _board(workspace_factory, team_factory)
        for i in range(3):  # 100% needs_human but under min_findings
            _handled_finding(workspace, owner, team, column, i, needs_human=True)

        assert list(AgentRunQualityDetector().execute(_context(workspace))) == []

    def test_findings_outside_window_are_ignored(self, workspace_factory, team_factory):
        workspace, owner, team, column = _board(workspace_factory, team_factory)
        rows = [_handled_finding(workspace, owner, team, column, i, needs_human=True) for i in range(6)]
        # Age every row out of the 24h window (bypasses auto_now).
        Task.objects.filter(id__in=[r.id for r in rows]).update(updated_at=datetime.now(UTC) - timedelta(hours=48))

        assert list(AgentRunQualityDetector().execute(_context(workspace))) == []

    def test_reads_run_telemetry_for_retry_metric(self, workspace_factory, team_factory):
        workspace, owner, team, column = _board(workspace_factory, team_factory)
        for i in range(5):
            _handled_finding(
                workspace,
                owner,
                team,
                column,
                i,
                telemetry={
                    "worker_retries": 1 if i < 4 else 0,
                    "budget_exceeded": None,
                    "rubric_verdicts": None,
                    "source_thread_id": f"t-{i}",
                },
            )

        results = list(AgentRunQualityDetector().execute(_context(workspace)))

        assert [r.payload["metric"] for r in results] == ["retry_rate"]
        assert results[0].payload["numerator"] == 4

    def test_never_calls_an_llm(self, workspace_factory, team_factory):
        # The POC hard rule: online evaluation is deterministic aggregation.
        workspace, owner, team, column = _board(workspace_factory, team_factory)
        for i in range(6):
            _handled_finding(workspace, owner, team, column, i, needs_human=True)

        with (
            mock.patch("components.knowledge.infrastructure.factories.llms.factory.LLMFactory.get_llm") as factory,
            mock.patch("components.knowledge.application.providers.ai_llm_provider.AILlmProvider") as provider,
        ):
            results = list(AgentRunQualityDetector().execute(_context(workspace)))

        assert results  # it did real work…
        factory.assert_not_called()  # …with zero model involvement
        provider.assert_not_called()

    def test_persists_through_the_normal_finding_path_and_is_router_safe(self, workspace_factory, team_factory):
        from components.agents.application.handlers.specialist_persistence_service import persist_finding_as_task
        from components.agents.infrastructure.adapters.actions.detectors.logwatch import AiFindingRouterDetector

        workspace, owner, team, column = _board(workspace_factory, team_factory)
        for i in range(6):
            _handled_finding(workspace, owner, team, column, i, needs_human=True)
        (result,) = AgentRunQualityDetector().execute(_context(workspace))

        task_id = persist_finding_as_task(
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

        card = Task.objects.get(id=task_id)
        assert card.source_type == SOURCE_TYPE
        # The router must never dispatch this card to a fix agent: its
        # source_type isn't routable AND its attribution alias is in the
        # router's non-specialist set.
        assert card.source_type not in AiFindingRouterDetector.ROUTABLE_SOURCE_TYPES
        assert card.metadata["agent_type"] in AiFindingRouterDetector._NON_SPECIALIST
        # Idempotent replay: same lookup_key → no duplicate card.
        assert (
            persist_finding_as_task(
                workspace=workspace,
                suggested_column=column,
                ai_user_id=str(owner.id),
                title=result.title,
                summary=result.summary,
                source_type=f"ai.{result.action_type}",
                agent_type="ai_teammate",
                detector_key=result.detector_slug,
                payload_data=result.payload,
                context=result.context,
                impact_score=50,
                idempotency_key=f"lookup_key:{result.payload['lookup_key']}",
            )
            is None
        )
