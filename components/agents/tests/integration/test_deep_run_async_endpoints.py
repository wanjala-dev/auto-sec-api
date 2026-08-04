"""Integration tests — deep/plan-and-run + deep/run-plan are ASYNC endpoints.

Root-cause regression guard for the api-pod restarts (exit 137): both
endpoints used to execute the WHOLE deep run (LLM planner + LangGraph
execution — minutes of wall-clock) synchronously inside the request path,
blocking the single daphne ASGI process past the k8s liveness timeout.

The contract now pinned here:

- POST returns **202** with the pending ``plan_id`` WITHOUT executing the run
  inline — the execution task is enqueued (after commit, IDs/primitives only)
  onto the ai-teammate worker's queue;
- a pending ``DeepRun`` row exists immediately, so the runs snapshot endpoint
  and the ``agent_run`` WS stream can be followed right away;
- the gates still refuse at the door (workspace AI paused → 503) without
  enqueueing anything;
- the worker task is idempotent under broker redelivery and always lands a
  terminal DeepRun status when the run fails before the runner takes over.
"""

from __future__ import annotations

from unittest import mock

import pytest

from components.agents.infrastructure.tasks import agent_tasks
from infrastructure.persistence.ai.agents.models import DeepRun, DeepRunLog

PLAN_AND_RUN_URL = "/ai/agents/deep/plan-and-run/"
RUN_PLAN_URL = "/ai/agents/deep/run-plan/"


@pytest.fixture
def ai_workspace(workspace_factory):
    """Workspace with the AI teammate enabled (the deep-run gate requires it)."""
    return workspace_factory(ai_teammate_enabled=True)


@pytest.mark.django_db
class TestDeepPlanAndRunEnqueues:
    def test_returns_202_and_enqueues_without_executing_inline(
        self, api_client, ai_workspace, django_capture_on_commit_callbacks
    ):
        api_client.force_authenticate(ai_workspace.workspace_owner)

        with mock.patch.object(agent_tasks.run_deep_plan_and_run, "delay") as delay:
            with django_capture_on_commit_callbacks(execute=True):
                response = api_client.post(
                    PLAN_AND_RUN_URL,
                    {"goal": "triage the new findings", "workspace_id": str(ai_workspace.id)},
                    format="json",
                )

        assert response.status_code == 202
        body = response.json()
        plan_id = body["plan_id"]
        assert plan_id
        assert body["status"] == "pending"
        assert body["state"]["status"] == "pending"

        # The pending row exists immediately — snapshot/WS surfaces work now.
        run = DeepRun.objects.get(thread_id=plan_id)
        assert run.status == DeepRun.STATUS_PENDING
        assert str(run.workspace_id) == str(ai_workspace.id)

        # Enqueued exactly once, IDs/primitives only (celery-tasks §0).
        delay.assert_called_once()
        kwargs = delay.call_args.kwargs
        assert kwargs["plan_id"] == plan_id
        assert kwargs["goal"] == "triage the new findings"
        assert kwargs["workspace_id"] == str(ai_workspace.id)
        assert kwargs["user_id"] == str(ai_workspace.workspace_owner_id)

    def test_ai_paused_workspace_is_refused_without_enqueue(
        self, api_client, workspace_factory, django_capture_on_commit_callbacks
    ):
        workspace = workspace_factory(ai_teammate_enabled=False)
        api_client.force_authenticate(workspace.workspace_owner)

        with mock.patch.object(agent_tasks.run_deep_plan_and_run, "delay") as delay:
            with django_capture_on_commit_callbacks(execute=True):
                response = api_client.post(
                    PLAN_AND_RUN_URL,
                    {"goal": "anything", "workspace_id": str(workspace.id)},
                    format="json",
                )

        assert response.status_code == 503
        assert response.json()["code"] == "ai_unavailable"
        delay.assert_not_called()
        assert not DeepRun.objects.exists()


@pytest.mark.django_db
class TestDeepRunPlanEnqueues:
    def test_returns_202_and_enqueues_validated_plan(
        self, api_client, ai_workspace, django_capture_on_commit_callbacks
    ):
        api_client.force_authenticate(ai_workspace.workspace_owner)

        with mock.patch.object(agent_tasks.run_deep_run_plan, "delay") as delay:
            with django_capture_on_commit_callbacks(execute=True):
                response = api_client.post(
                    RUN_PLAN_URL,
                    {
                        "plan": {"goal": "run the prepared plan", "tasks": []},
                        "workspace_id": str(ai_workspace.id),
                    },
                    format="json",
                )

        assert response.status_code == 202
        body = response.json()
        plan_id = body["plan_id"]
        assert body["status"] == "pending"

        run = DeepRun.objects.get(thread_id=plan_id)
        assert run.status == DeepRun.STATUS_PENDING

        delay.assert_called_once()
        kwargs = delay.call_args.kwargs
        assert kwargs["thread_id"] == plan_id
        assert kwargs["raw_plan"]["plan_id"] == plan_id
        assert kwargs["workspace_id"] == str(ai_workspace.id)

    def test_invalid_plan_is_rejected_before_enqueue(
        self, api_client, ai_workspace, django_capture_on_commit_callbacks
    ):
        api_client.force_authenticate(ai_workspace.workspace_owner)

        with mock.patch.object(agent_tasks.run_deep_run_plan, "delay") as delay:
            with django_capture_on_commit_callbacks(execute=True):
                response = api_client.post(
                    RUN_PLAN_URL,
                    # tasks must be a list of TaskSpec dicts — force a
                    # PlanSpec validation error at the API boundary.
                    {"plan": {"goal": "bad", "tasks": "not-a-list"}, "workspace_id": str(ai_workspace.id)},
                    format="json",
                )

        assert response.status_code == 400
        delay.assert_not_called()
        assert not DeepRun.objects.exists()


@pytest.mark.django_db
class TestRunDeepPlanAndRunTask:
    """The worker side: idempotency + terminal-status guarantees."""

    def _task_kwargs(self, workspace, plan_id="plan-1"):
        return {
            "goal": "g",
            "plan_id": plan_id,
            "agent_type": "task_agent",
            "user_id": str(workspace.workspace_owner_id),
            "workspace_id": str(workspace.id),
        }

    def test_replay_of_terminal_run_is_a_noop(self, ai_workspace):
        DeepRun.objects.create(
            thread_id="plan-1",
            plan_id="plan-1",
            user=ai_workspace.workspace_owner,
            workspace=ai_workspace,
            status=DeepRun.STATUS_COMPLETED,
        )
        with mock.patch("components.agents.application.service.AgentsService") as service_cls:
            result = agent_tasks.run_deep_plan_and_run.apply(kwargs=self._task_kwargs(ai_workspace)).get()

        service_cls.assert_not_called()
        assert result["skipped"] == DeepRun.STATUS_COMPLETED

    def test_run_owned_by_another_task_is_skipped(self, ai_workspace):
        DeepRun.objects.create(
            thread_id="plan-1",
            plan_id="plan-1",
            user=ai_workspace.workspace_owner,
            workspace=ai_workspace,
            status=DeepRun.STATUS_RUNNING,
            state={"celery_task_id": "someone-else"},
        )
        with mock.patch("components.agents.application.service.AgentsService") as service_cls:
            result = agent_tasks.run_deep_plan_and_run.apply(
                kwargs=self._task_kwargs(ai_workspace),
                task_id="this-delivery",
            ).get()

        service_cls.assert_not_called()
        assert result["skipped"] == "already_running"

    def test_pre_runner_failure_lands_terminal_failed_status(self, ai_workspace):
        from components.agents.application.commands.deep_run_command import DeepRunFailure

        DeepRun.objects.create(
            thread_id="plan-1",
            plan_id="plan-1",
            user=ai_workspace.workspace_owner,
            workspace=ai_workspace,
            status=DeepRun.STATUS_PENDING,
        )
        service = mock.Mock()
        service.deep_plan_and_run.return_value = DeepRunFailure(error="planner exploded", status_code=500)
        with mock.patch("components.agents.application.service.AgentsService", return_value=service):
            result = agent_tasks.run_deep_plan_and_run.apply(kwargs=self._task_kwargs(ai_workspace)).get()

        assert result == {"success": False, "plan_id": "plan-1", "error": "planner exploded"}
        run = DeepRun.objects.get(thread_id="plan-1")
        assert run.status == DeepRun.STATUS_FAILED
        assert run.last_error == "planner exploded"
        # The WS/DeepRunLog stream got its terminal event too.
        assert DeepRunLog.objects.filter(deep_run=run, event_type="run_failed").exists()

    def test_gate_exception_lands_terminal_failed_status(self, ai_workspace):
        """Kill switch flipped / quota exhausted between enqueue and execution."""
        from components.agents.domain.errors import AiUnavailable

        DeepRun.objects.create(
            thread_id="plan-1",
            plan_id="plan-1",
            user=ai_workspace.workspace_owner,
            workspace=ai_workspace,
            status=DeepRun.STATUS_PENDING,
        )
        service = mock.Mock()
        service.deep_plan_and_run.side_effect = AiUnavailable(workspace_id=str(ai_workspace.id))
        with mock.patch("components.agents.application.service.AgentsService", return_value=service):
            result = agent_tasks.run_deep_plan_and_run.apply(kwargs=self._task_kwargs(ai_workspace)).get()

        assert result["success"] is False
        run = DeepRun.objects.get(thread_id="plan-1")
        assert run.status == DeepRun.STATUS_FAILED
        assert run.last_error
