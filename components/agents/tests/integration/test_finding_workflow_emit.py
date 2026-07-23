"""The finding-materialization path emits ``finding_*`` workflow triggers.

When a detector/specialist files a finding via ``persist_finding_as_task``, a
``WorkflowEvent`` is emitted so alert-driven playbooks can fire:
``finding_raised`` for every finding, plus a severity-scoped trigger
(``finding_high`` / ``finding_critical``) when the band matches.
"""

from __future__ import annotations

import pytest

from components.agents.application.handlers.specialist_persistence_service import (
    persist_finding_as_task,
)
from infrastructure.persistence.project.models import Column
from infrastructure.persistence.workspaces.workflows.models import WorkflowEvent

pytestmark = pytest.mark.django_db


def _board(workspace_factory, team_factory):
    workspace = workspace_factory()
    owner = workspace.workspace_owner
    team = team_factory(workspace=workspace, created_by=owner, members=[owner])
    column = Column.objects.create(
        team=team, workspace=workspace, project=None, title="Backlog", order=0, created_by=owner
    )
    return workspace, owner, column


def _file_finding(workspace, owner, column, *, impact_score, key, service="web"):
    return persist_finding_as_task(
        workspace=workspace,
        suggested_column=column,
        ai_user_id=str(owner.id),
        title="[FINDING] web · Internal Server Error",
        summary="500s spiking on web",
        source_type="ai.log_watch",
        agent_type="triage_agent",
        detector_key="logwatch.error",
        payload_data={"service": service, "signal": "ERROR in web"},
        context={},
        impact_score=impact_score,
        idempotency_key=key,
    )


class TestFindingWorkflowEmit:
    def test_high_finding_emits_raised_and_high(self, workspace_factory, team_factory):
        workspace, owner, column = _board(workspace_factory, team_factory)
        task_id = _file_finding(workspace, owner, column, impact_score=80, key="wf-emit-high")

        assert task_id is not None
        events = WorkflowEvent.objects.filter(source_type="finding", source_id=str(task_id))
        assert set(events.values_list("trigger_type", flat=True)) == {"finding_raised", "finding_high"}
        raised = events.get(trigger_type="finding_raised")
        assert raised.payload["severity"] == "high"
        assert raised.payload["service"] == "web"
        assert raised.payload["task_id"] == str(task_id)

    def test_low_finding_emits_only_raised(self, workspace_factory, team_factory):
        workspace, owner, column = _board(workspace_factory, team_factory)
        task_id = _file_finding(workspace, owner, column, impact_score=10, key="wf-emit-low", service="nginx")

        triggers = set(
            WorkflowEvent.objects.filter(source_type="finding", source_id=str(task_id)).values_list(
                "trigger_type", flat=True
            )
        )
        assert triggers == {"finding_raised"}

    def test_idempotent_replay_does_not_double_emit(self, workspace_factory, team_factory):
        workspace, owner, column = _board(workspace_factory, team_factory)
        _file_finding(workspace, owner, column, impact_score=80, key="wf-emit-dup")
        # Same idempotency_key → the finding write is a no-op (returns None), so
        # no second batch of workflow events is emitted.
        second = _file_finding(workspace, owner, column, impact_score=80, key="wf-emit-dup")
        assert second is None
        assert WorkflowEvent.objects.filter(source_type="finding", trigger_type="finding_raised").count() == 1
