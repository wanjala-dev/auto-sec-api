"""Integration tests: the ``ai`` node actually runs, and never strands the graph.

The shipped ``CNAPP — Auto-Triage Critical & High`` starter is
``start -> condition(critical|high) -> ai(triage) -> message(notify) -> end``.
Every critical/high finding therefore has to pass THROUGH the ai node to reach
the notify leg. These tests lock three properties of that node:

1. **It runs.** ``_execute_ai`` reaches the agents context and queues a real
   deep run for the workspace, attributed to the workspace's AI teammate
   identity. (It used to import a class name that does not exist —
   ``AgentService`` instead of ``AgentsService`` — so the node raised on every
   invocation and ``notify`` was unreachable for 100% of critical/high
   findings.)
2. **A governance stop is a skip, not a failure.** When the workspace has AI
   paused, the node is an explicit no-op and the run walks on to ``notify``.
   A paused workspace must still be told about its critical finding.
3. **A missing actor still fails loudly.** No silent no-op: if there is no
   principal to attribute the AI run to, the node raises.

Hermetic by construction, no LLM call: ``enqueue_plan_and_run`` writes the
pending ``DeepRun`` row synchronously and dispatches the Celery task from a
``transaction.on_commit`` hook. These tests deliberately do NOT capture
on-commit callbacks, so the row (the assertion) is written while the task (the
LLM) never fires.
"""

from __future__ import annotations

import pytest

from components.agents.application.facades.ai_teammate_facade import ensure_ai_identity
from components.workflow.application.service import WorkflowService
from components.workflow.domain.errors import WorkflowActionError
from components.workflow.infrastructure.adapters.node_actions import execute_node_action
from components.workflow.infrastructure.tasks.workflow_tasks import workflow_run_start
from infrastructure.persistence.ai.agents.models import DeepRun
from infrastructure.persistence.workspaces.workflows.models import (
    Workflow,
    WorkflowRun,
    WorkflowStepState,
)

pytestmark = pytest.mark.django_db


# --- builders --------------------------------------------------------------
AI_PROMPT = "Triage this finding and recommend whether it needs immediate action."


def _cnapp_graph():
    """The shipped ``cnapp-high-priority-triage`` shape: the notify leg sits
    BEHIND the ai node, so a raising ai node makes notify unreachable."""
    return {
        "nodes": [
            {"id": "start", "type": "start", "label": "Finding raised", "config": {"triggerType": "finding_raised"}},
            {
                "id": "severe",
                "type": "condition",
                "label": "Critical or high?",
                "config": {
                    "predicate": {
                        "match": "any",
                        "conditions": [
                            {"field": "severity", "op": "eq", "value": "critical"},
                            {"field": "severity", "op": "eq", "value": "high"},
                        ],
                    }
                },
            },
            {"id": "triage", "type": "ai", "label": "AI triage", "config": {"prompt": AI_PROMPT}},
            {
                "id": "notify",
                "type": "message",
                "label": "Notify the team",
                "config": {"channel": "in_app", "body": "A critical/high finding was triaged automatically."},
            },
            {"id": "logit", "type": "message", "label": "Log", "config": {"channel": "in_app", "body": "Recorded."}},
            {"id": "end", "type": "end", "label": "End", "config": {}},
        ],
        "edges": [
            {"id": "e0", "from": "start", "to": "severe"},
            {"id": "e1", "from": "severe", "to": "triage", "label": "yes"},
            {"id": "e2", "from": "severe", "to": "logit", "label": "no"},
            {"id": "e3", "from": "triage", "to": "notify"},
            {"id": "e4", "from": "notify", "to": "end"},
            {"id": "e5", "from": "logit", "to": "end"},
        ],
    }


def _ai_workspace(workspace_factory):
    """A workspace with AI switched on and the AI teammate identity every real
    workspace gets at bootstrap (``ensure_agents_board`` -> ``ensure_ai_identity``).

    Both are how the live demo workspace is configured: 18/18 cluster
    workspaces carry the teammate identity and the demo org has
    ``ai_teammate_enabled=True``.
    """
    workspace = workspace_factory()
    workspace.ai_teammate_enabled = True
    workspace.save(update_fields=["ai_teammate_enabled"])
    ensure_ai_identity(workspace)
    return workspace


def _workflow(workspace, graph=None):
    return Workflow.objects.create(
        workspace=workspace,
        name="CNAPP — Auto-Triage Critical & High",
        goal="general",
        status=Workflow.Status.PUBLISHED,
        version=1,
        # Auto-seeded starter workflows carry created_by=None — the actor for
        # the AI run must therefore come from the workspace, not the owner.
        created_by=None,
        graph=graph if graph is not None else {"nodes": [], "edges": []},
    )


def _finding_run(workflow, *, severity="critical", status=WorkflowRun.Status.RUNNING):
    return WorkflowRun.objects.create(
        workflow=workflow,
        workflow_version=1,
        status=status,
        trigger_type="finding_raised",
        trigger_payload={"severity": severity, "finding_id": "finding-1"},
        target_type="finding",
        target_id="finding-1",
    )


def _ai_node(config=None):
    return {"id": "triage", "type": "ai", "label": "AI triage", "config": config or {"prompt": AI_PROMPT}}


class TestAiNodeQueuesADeepRun:
    def test_ai_node_queues_a_deep_run_for_the_workspace(self, workspace_factory):
        workspace = _ai_workspace(workspace_factory)
        run = _finding_run(_workflow(workspace))
        config = {"prompt": AI_PROMPT}

        out = execute_node_action(run, _ai_node(config), config)

        assert out["status"] == "queued", out
        assert out["plan_id"]

        deep_run = DeepRun.objects.filter(workspace_id=workspace.id, thread_id=out["plan_id"]).first()
        assert deep_run is not None, "the ai node must persist a real deep run for the workspace"
        assert deep_run.status == DeepRun.STATUS_PENDING
        # Attributed to the workspace's AI teammate identity, not a fake user.
        assert str(deep_run.user_id) == str(ensure_ai_identity(workspace)[1].id)

    def test_ai_node_without_a_prompt_is_skipped_not_failed(self, workspace_factory):
        workspace = _ai_workspace(workspace_factory)
        run = _finding_run(_workflow(workspace))

        out = execute_node_action(run, _ai_node({}), {})

        assert out["status"] == "skipped"
        assert not DeepRun.objects.filter(workspace_id=workspace.id).exists()

    def test_paused_workspace_ai_skips_the_node_instead_of_failing_the_run(self, workspace_factory):
        """A governance stop must not strand the notify leg behind a failed run."""
        workspace = _ai_workspace(workspace_factory)
        workspace.ai_teammate_enabled = False
        workspace.save(update_fields=["ai_teammate_enabled"])
        run = _finding_run(_workflow(workspace))
        config = {"prompt": AI_PROMPT}

        out = execute_node_action(run, _ai_node(config), config)

        assert out["status"] == "skipped"
        assert "paused" in out["reason"].lower()
        assert not DeepRun.objects.filter(workspace_id=workspace.id).exists()

    def test_no_resolvable_actor_fails_loudly(self, workspace_factory):
        """No principal to attribute the run to is a real misconfiguration —
        never a silent success."""
        workspace = workspace_factory()  # deliberately no AI teammate identity
        run = _finding_run(_workflow(workspace))
        config = {"prompt": AI_PROMPT}

        with pytest.raises(WorkflowActionError, match="no actor"):
            execute_node_action(run, _ai_node(config), config)


class TestCnappGraphReachesNotify:
    def test_critical_finding_reaches_the_notify_node(self, workspace_factory):
        """The whole point of the bug: notify sits behind the ai node."""
        workspace = _ai_workspace(workspace_factory)
        workflow = _workflow(workspace, _cnapp_graph())
        WorkflowService().publish_workflow(workflow)
        run = _finding_run(workflow, severity="critical", status=WorkflowRun.Status.QUEUED)

        workflow_run_start(str(run.id))

        run.refresh_from_db()
        triage_state = WorkflowStepState.objects.filter(run=run, node_id="triage").first()
        notify_state = WorkflowStepState.objects.filter(run=run, node_id="notify").first()

        assert triage_state is not None and triage_state.status == "completed", (
            f"ai node did not complete: {getattr(triage_state, 'last_error', None)}"
        )
        assert notify_state is not None, "the notify leg was never reached — it sits behind the ai node"
        assert run.status == WorkflowRun.Status.COMPLETED, run.status
