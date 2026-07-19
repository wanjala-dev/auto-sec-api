"""End-to-end integration tests for the log-finding consumer pipeline (#47 + #50).

Real DB; only the LLM advisor is stubbed (the external boundary). Covers the
SHARED finding-processing core used by BOTH the triage agent (error findings)
and the optimization agent (pattern findings):

* a pending finding is advised, commented, moved to the acting column, stamped
  handled, and gains a provenance event recording which agent acted + when;
* a second run is a concurrency-safe no-op (no duplicate comment / move);
* creation provenance is stamped by ``persist_finding_as_task``;
* the TaskSerializer surfaces both the optimization contract and the provenance
  strip.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest import mock

import pytest

from infrastructure.persistence.project.models import Column, Task, TaskComment


def _board(workspace_factory, team_factory):
    workspace = workspace_factory()
    owner = workspace.workspace_owner
    team = team_factory(workspace=workspace, created_by=owner, members=[owner])
    intake = Column.objects.create(
        team=team, workspace=workspace, project=None, title="Backlog", order=0, created_by=owner
    )
    return workspace, owner, team, intake


def _agent(workspace, owner):
    return SimpleNamespace(workspace_id=str(workspace.id), user_id=str(owner.id))


def _opt_task(workspace, owner, team, column):
    return Task.objects.create(
        team=team,
        workspace=workspace,
        column=column,
        created_by=owner,
        title="[OPTIMIZE] celery_beat · over-scheduled workflow.run_due_schedules",
        source_type="ai.log_optimization",
        metadata={
            "agent_type": "optimization_agent",
            "detector": "logwatch.optimization",
            "provenance": {
                "created_by_kind": "detector",
                "detector": "logwatch.optimization",
                "assigned_specialist": "optimization_agent",
                "created_at": "2026-07-19T00:00:00+00:00",
                "events": [{"actor": "detector:logwatch.optimization", "action": "filed finding", "at": "t0"}],
            },
            "payload": {
                "kind": "periodic_task",
                "service": "celery_beat",
                "subject": "workflow.run_due_schedules",
                "signal": "over-scheduled",
                "frequency": {"last_window": 41, "runs_observed": 3},
                "blast_radius": {"share_pct": 8.2},
                "recommendation": "",
                "triage": {"status": "pending"},
            },
        },
    )


@pytest.mark.django_db
class TestOptimizationPipeline:
    def test_advise_moves_card_and_records_provenance(self, workspace_factory, team_factory):
        from components.agents.infrastructure.adapters.langchain.tools import optimization_agent as tools
        from components.integrations.application.log_optimization_advisor_service import OptimizationSuggestion

        workspace, owner, team, intake = _board(workspace_factory, team_factory)
        task = _opt_task(workspace, owner, team, intake)
        agent = _agent(workspace, owner)

        suggestion = OptimizationSuggestion(
            assessment="Fires far more often than the work requires.",
            recommendation="Raise the beat interval from */5 to */15.",
            resource_win="~66% fewer scheduler wakeups",
            confidence="high",
        )
        with mock.patch(
            "components.integrations.application.log_optimization_advisor_service.LogOptimizationAdvisor.suggest",
            return_value=suggestion,
        ):
            result = tools.advise_optimization(agent, str(task.id))

        assert "Handled" in result
        task.refresh_from_db()
        assert task.column.title == "Optimize"
        meta = task.metadata
        assert meta["triage"]["status"] == "triaged"
        assert meta["triage"]["agent"] == "optimization_agent"
        assert meta["payload"]["recommendation"] == "Raise the beat interval from */5 to */15."
        assert meta["payload"]["resource_win"] == "~66% fewer scheduler wakeups"
        # Provenance grew an agent event on top of the detector's file event.
        actors = [e["actor"] for e in meta["provenance"]["events"]]
        assert "detector:logwatch.optimization" in actors
        assert "agent:optimization_agent" in actors
        assert meta["provenance"]["last_handled_by"] == "optimization_agent"
        assert TaskComment.objects.filter(task=task).count() == 1

    def test_second_advise_is_concurrency_safe_noop(self, workspace_factory, team_factory):
        from components.agents.infrastructure.adapters.langchain.tools import optimization_agent as tools
        from components.integrations.application.log_optimization_advisor_service import OptimizationSuggestion

        workspace, owner, team, intake = _board(workspace_factory, team_factory)
        task = _opt_task(workspace, owner, team, intake)
        agent = _agent(workspace, owner)
        suggestion = OptimizationSuggestion(assessment="a", recommendation="do x", resource_win="", confidence="low")

        with mock.patch(
            "components.integrations.application.log_optimization_advisor_service.LogOptimizationAdvisor.suggest",
            return_value=suggestion,
        ):
            tools.advise_optimization(agent, str(task.id))
            second = tools.advise_optimization(agent, str(task.id))

        assert "already handled" in second.lower()
        assert TaskComment.objects.filter(task=task).count() == 1  # no duplicate

    def test_ungrounded_suggestion_is_flagged_needs_human(self, workspace_factory, team_factory):
        # A vague recommendation (no concrete change) fails the grounded verifier;
        # after a re-advise it's still vague → committed but downgraded + flagged
        # for a human, never shipped as a confident fix.
        from components.agents.infrastructure.adapters.langchain.tools import optimization_agent as tools
        from components.integrations.application.log_optimization_advisor_service import OptimizationSuggestion

        workspace, owner, team, intake = _board(workspace_factory, team_factory)
        task = _opt_task(workspace, owner, team, intake)
        agent = _agent(workspace, owner)
        vague = OptimizationSuggestion(
            assessment="It is noisy.",
            recommendation="Monitor the system and review the logs.",  # no concrete change
            resource_win="",
            confidence="high",
        )
        with mock.patch(
            "components.integrations.application.log_optimization_advisor_service.LogOptimizationAdvisor.suggest",
            return_value=vague,
        ):
            result = tools.advise_optimization(agent, str(task.id))

        assert "human review" in result.lower()
        task.refresh_from_db()
        meta = task.metadata
        assert meta["triage"]["needs_human"] is True
        assert meta["payload"]["needs_human"] is True
        assert meta["payload"]["confidence"] == "low"  # downgraded from "high"


@pytest.mark.django_db
class TestPendingQueryNullSafety:
    def test_fresh_finding_without_triage_key_is_still_pending(self, workspace_factory, team_factory):
        """Regression: a finding with NO top-level ``metadata.triage`` key must
        still be seen as pending. ``.exclude(metadata__triage__status='triaged')``
        drops it (Postgres NULL-in-NOT trap), which hid every un-stamped finding
        from the router until the NULL-safe ``not_triaged_filter`` landed.
        """
        from components.agents.infrastructure.adapters.langchain.tools._finding_processing import (
            pending_findings_qs,
        )

        workspace, owner, team, intake = _board(workspace_factory, team_factory)
        Task.objects.create(
            team=team,
            workspace=workspace,
            column=intake,
            created_by=owner,
            title="[OPTIMIZE] fresh pattern",
            source_type="ai.log_optimization",
            # NOTE: NO top-level "triage" key — exactly how a freshly-filed
            # finding looks before any agent stamps it.
            metadata={"agent_type": "optimization_agent", "payload": {"kind": "volume"}},
        )
        pending = pending_findings_qs(str(workspace.id), "ai.log_optimization")
        assert len(pending) == 1, "fresh finding must be pending even without a triage key"

    def test_triaged_finding_is_excluded(self, workspace_factory, team_factory):
        from components.agents.infrastructure.adapters.langchain.tools._finding_processing import (
            pending_findings_qs,
        )

        workspace, owner, team, intake = _board(workspace_factory, team_factory)
        Task.objects.create(
            team=team,
            workspace=workspace,
            column=intake,
            created_by=owner,
            title="handled",
            source_type="ai.log_optimization",
            metadata={"agent_type": "optimization_agent", "triage": {"status": "triaged"}, "payload": {}},
        )
        assert pending_findings_qs(str(workspace.id), "ai.log_optimization") == []


@pytest.mark.django_db
class TestTriagePipeline:
    def test_triage_moves_card_to_triage_column(self, workspace_factory, team_factory):
        from components.agents.infrastructure.adapters.langchain.tools import triage_agent as tools
        from components.integrations.application.log_fix_advisor_service import FixSuggestion

        workspace, owner, team, intake = _board(workspace_factory, team_factory)
        task = Task.objects.create(
            team=team,
            workspace=workspace,
            column=intake,
            created_by=owner,
            title="[HIGH] celery_worker · ImportError",
            source_type="ai.log_watch",
            metadata={
                "agent_type": "triage_agent",
                "detector": "logwatch.error",
                "provenance": {"detector": "logwatch.error", "events": []},
                "payload": {
                    "service": "celery_worker",
                    "level": "ERROR",
                    "message": "cannot import name 'X'",
                    "triage": {"status": "pending"},
                },
            },
        )
        agent = _agent(workspace, owner)
        suggestion = FixSuggestion(
            likely_cause="Missing export.", suggested_fix="Add X to the module.", confidence="high"
        )
        with mock.patch(
            "components.integrations.application.log_fix_advisor_service.LogFixAdvisor.suggest",
            return_value=suggestion,
        ):
            result = tools.triage_finding(agent, str(task.id))

        assert "Handled" in result
        task.refresh_from_db()
        assert task.column.title == "Triage"
        assert task.metadata["payload"]["suggested_fix"] == "Add X to the module."
        assert task.metadata["triage"]["agent"] == "triage_agent"


@pytest.mark.django_db
class TestCreationProvenanceAndSerializer:
    def test_persist_finding_stamps_creation_provenance(self, workspace_factory, team_factory):
        from components.agents.application.handlers.specialist_persistence_service import persist_finding_as_task

        workspace, owner, team, intake = _board(workspace_factory, team_factory)
        task_id = persist_finding_as_task(
            workspace=workspace,
            suggested_column=intake,
            ai_user_id=str(owner.id),
            title="[OPTIMIZE] noisy task",
            summary="fires a lot",
            source_type="ai.log_optimization",
            agent_type="optimization_agent",
            detector_key="logwatch.optimization",
            payload_data={"confidence": "high", "kind": "periodic_task"},
            context={},
            impact_score=60,
            idempotency_key="logopt:sig-1",
        )
        assert task_id is not None
        task = Task.objects.get(id=task_id)
        prov = task.metadata["provenance"]
        assert prov["created_by_kind"] == "detector"
        assert prov["detector"] == "logwatch.optimization"
        assert prov["assigned_specialist"] == "optimization_agent"
        assert prov["confidence"] == "high"
        assert prov["created_at"]
        assert prov["events"][0]["actor"] == "detector:logwatch.optimization"

    def test_serializer_surfaces_optimization_and_provenance(self, workspace_factory, team_factory):
        from components.project.mappers.rest.project_serializers import TaskSerializer

        workspace, owner, team, intake = _board(workspace_factory, team_factory)
        task = _opt_task(workspace, owner, team, intake)
        data = TaskSerializer(task).data

        lw = data["log_watch"]
        assert lw is not None
        assert lw["kind"] == "periodic_task"
        assert lw["subject"] == "workflow.run_due_schedules"
        assert lw["frequency"]["last_window"] == 41
        prov = data["provenance"]
        assert prov is not None
        assert prov["detector"] == "logwatch.optimization"
        assert prov["assigned_specialist"] == "optimization_agent"
