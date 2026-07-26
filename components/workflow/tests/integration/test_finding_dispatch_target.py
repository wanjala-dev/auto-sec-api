"""E2E: a finding filed by the REAL persistence path starts a workflow run that
targets the finding.

Regression for the two dispatch bugs (issues #89 / #90):

  1. ``_emit_finding_triggers`` builds a payload with NO ``target_id`` — it sets
     ``source_id`` = the finding's board-Task id, intending the run to target the
     finding. ``dispatch_event`` read the target only from
     ``payload["target_id"]`` / ``["contact_id"]`` and dropped every finding event
     as ``workflow_event_dropped no_target`` — so the seeded finding→SOAR playbooks
     never started a run.
  2. Even had a run started, ``run.target`` resolved to a CRM contact; there was no
     first-class finding target.

The fix derives ``target_type="finding", target_id=<source_id>`` for self-targeting
sources (``SELF_TARGETING_SOURCE_TYPES``). This test drives the real emitter
(``persist_finding_as_task``) so the payload shape is exactly production's, then
dispatches the emitted event and asserts a run starts and targets the finding.

Note: we bind ``finding_high`` (not ``finding_critical``) because
``_derive_severity`` caps at "high" — ``finding_critical`` is never emitted today.
That is a separate, tracked issue; here we lock the dispatch behaviour against a
trigger the emitter actually produces.
"""

from __future__ import annotations

import pytest

from components.agents.application.handlers.specialist_persistence_service import (
    persist_finding_as_task,
)
from components.workflow.application.service import WorkflowService
from components.workflow.infrastructure.adapters.dispatcher import dispatch_event
from infrastructure.persistence.project.models import Column
from infrastructure.persistence.workspaces.workflows.models import (
    Workflow,
    WorkflowEvent,
    WorkflowRun,
)

pytestmark = [pytest.mark.django_db]


def _board(workspace_factory, team_factory):
    workspace = workspace_factory()
    owner = workspace.workspace_owner
    team = team_factory(workspace=workspace, created_by=owner, members=[owner])
    column = Column.objects.create(
        team=team, workspace=workspace, project=None, title="Backlog", order=0, created_by=owner
    )
    return workspace, owner, column


def _high_finding_graph(trigger_type: str = "finding_high"):
    # Mirrors the seeded finding playbooks' shape: start(finding trigger) -> ai
    # triage -> end. The AI node is what must run ON the finding; it reads
    # run.target_type / target_id (a message node would just skip on a non-contact
    # target — that is correct until item #5 adds SOC-shaped actions).
    return {
        "nodes": [
            {"id": "start", "type": "start", "label": "High finding", "config": {"triggerType": trigger_type}},
            {"id": "triage", "type": "ai", "label": "AI triage", "config": {"prompt": "Triage this finding."}},
            {"id": "end", "type": "end", "label": "End", "config": {}},
        ],
        "edges": [
            {"id": "e0", "from": "start", "to": "triage"},
            {"id": "e1", "from": "triage", "to": "end"},
        ],
    }


def _publish_finding_workflow(workspace, trigger_type: str = "finding_high"):
    wf = Workflow.objects.create(
        workspace=workspace,
        name="High finding alert",
        goal="general",
        status="draft",
        graph=_high_finding_graph(trigger_type),
    )
    WorkflowService().publish_workflow(wf)
    return wf


def _file_high_finding(workspace, owner, column, *, key="wf-dispatch-high"):
    return persist_finding_as_task(
        workspace=workspace,
        suggested_column=column,
        ai_user_id=str(owner.id),
        title="[FINDING] web · Internal Server Error",
        summary="500s spiking on web",
        source_type="ai.log_watch",
        agent_type="triage_agent",
        detector_key="logwatch.error",
        payload_data={"service": "web", "signal": "ERROR in web"},
        context={},
        impact_score=85,  # >= 70 -> "high" -> emits finding_raised + finding_high
        idempotency_key=key,
    )


class TestFindingDispatchTargetsTheFinding:
    def test_real_emitter_payload_starts_a_run_targeting_the_finding(self, workspace_factory, team_factory):
        workspace, owner, column = _board(workspace_factory, team_factory)
        _publish_finding_workflow(workspace, trigger_type="finding_high")

        task_id = _file_high_finding(workspace, owner, column)
        assert task_id is not None

        # The real emitter created the finding_high event with NO target_id and
        # source_id = the finding's task id. This is the exact bug precondition.
        event = WorkflowEvent.objects.get(source_type="finding", source_id=str(task_id), trigger_type="finding_high")
        assert "target_id" not in event.payload
        assert event.payload.get("contact_id") is None
        assert event.source_id == str(task_id)

        created = dispatch_event(event)

        # No longer dropped: a run starts and TARGETS the finding.
        assert created == 1
        run = WorkflowRun.objects.get(workflow__workspace_id=workspace.id)
        assert run.target_type == "finding"
        assert run.target_id == str(task_id)
        # The finding payload rides along so condition/ai nodes can branch on it.
        assert run.trigger_payload.get("severity") == "high"
        assert run.trigger_payload.get("service") == "web"

    def test_explicit_contact_target_is_not_overridden_by_finding_source(self, workspace_factory):
        # The self-target derivation is a FALLBACK only: an event that carries an
        # explicit contact target must keep it (never clobbered by source_id).
        workspace = workspace_factory()
        _publish_finding_workflow(workspace, trigger_type="finding_raised")
        event = WorkflowEvent.objects.create(
            workspace_id=str(workspace.id),
            source_type="finding",
            source_id="task-abc",
            trigger_type="finding_raised",
            payload={"target_type": "contact", "target_id": "contact-xyz"},
        )

        assert dispatch_event(event) == 1
        run = WorkflowRun.objects.get(workflow__workspace_id=workspace.id)
        assert run.target_type == "contact"
        assert run.target_id == "contact-xyz"
