"""Integration test: ``task_moved_column`` workflow trigger.

Phase 4 of the Agents-as-Teammates migration adds an end-to-end chain:

    Kanban move → ``task_moved_column`` workflow event →
    matched binding → workflow run → ``publish_event`` node →
    ``TaskAcceptedFromBoard`` shared-kernel event

This test pins the emission half (move → event row). The downstream
"workflow run executes and publishes the shared-kernel event" piece is
covered by a separate test that drives the workflow engine directly.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from components.project.application.ports.batch_move_tasks_port import (
    BatchMoveTasksCommand,
    TaskMove,
)
from components.project.infrastructure.repositories.batch_move_tasks_repository import (
    OrmBatchMoveTasksRepository,
)


def _captured_emits(emit_mock):
    return [call.kwargs for call in emit_mock.call_args_list]


@pytest.mark.django_db
class TestBatchMoveTasksEmitsColumnMove:
    def test_batch_move_emits_task_moved_column_per_distinct_move(
        self, workspace_factory, team_factory, user_factory,
        django_capture_on_commit_callbacks,
    ):
        from infrastructure.persistence.project.models import Column, Project, Task

        workspace = workspace_factory()
        owner = workspace.workspace_owner
        team = team_factory(workspace=workspace, created_by=owner, members=[owner])
        project = Project.objects.create(
            workspace=workspace, team=team, title="Demo", created_by=owner,
        )
        suggested = Column.objects.create(
            workspace=workspace, team=team, project=project,
            title="Suggested", order=0, created_by=owner,
        )
        accepted = Column.objects.create(
            workspace=workspace, team=team, project=project,
            title="Accepted", order=1, created_by=owner,
        )
        task = Task.objects.create(
            workspace=workspace, team=team, project=project,
            column=suggested, created_by=owner,
            title="AI finding", source_type="ai.book_balance.budget_overrun",
        )

        # The emit is deferred via transaction.on_commit; capture + execute
        # the callbacks so it fires while the patch is still active.
        repo = OrmBatchMoveTasksRepository()
        with patch(
            "components.workflow.infrastructure.adapters.dispatcher."
            "emit_workflow_event"
        ) as emit_mock:
            with django_capture_on_commit_callbacks(execute=True):
                repo.batch_move_tasks(
                    command=BatchMoveTasksCommand(
                        user_id=str(owner.id),
                        moves=[
                            TaskMove(
                                task_id=str(task.id),
                                column_id=str(accepted.id),
                                order=0,
                            ),
                        ],
                    )
                )

        emits = _captured_emits(emit_mock)
        moved = [e for e in emits if e.get("trigger_type") == "task_moved_column"]
        assert len(moved) == 1
        payload = moved[0]["payload"]
        assert payload["task_id"] == str(task.id)
        assert payload["previous_column_id"] == str(suggested.id)
        assert payload["new_column_id"] == str(accepted.id)
        assert payload["task_source_type"] == "ai.book_balance.budget_overrun"
        assert payload["target_type"] == "group"
        assert payload["target_id"] == str(workspace.id)

    def test_batch_move_skips_emit_when_target_column_equals_current(
        self, workspace_factory, team_factory
    ):
        """A no-op move (target = current column) must not fire the
        trigger — otherwise the engine would log spurious runs every
        time a card is re-ordered within the same column."""
        from infrastructure.persistence.project.models import Column, Project, Task

        workspace = workspace_factory()
        owner = workspace.workspace_owner
        team = team_factory(workspace=workspace, created_by=owner, members=[owner])
        project = Project.objects.create(
            workspace=workspace, team=team, title="Demo", created_by=owner,
        )
        column = Column.objects.create(
            workspace=workspace, team=team, project=project,
            title="Suggested", order=0, created_by=owner,
        )
        task = Task.objects.create(
            workspace=workspace, team=team, project=project,
            column=column, created_by=owner, title="t",
        )

        repo = OrmBatchMoveTasksRepository()
        with patch(
            "components.workflow.infrastructure.adapters.dispatcher."
            "emit_workflow_event"
        ) as emit_mock:
            repo.batch_move_tasks(
                command=BatchMoveTasksCommand(
                    user_id=str(owner.id),
                    moves=[
                        TaskMove(
                            task_id=str(task.id),
                            column_id=str(column.id),
                            order=5,
                        ),
                    ],
                )
            )

        emits = _captured_emits(emit_mock)
        moved = [e for e in emits if e.get("trigger_type") == "task_moved_column"]
        assert moved == []


@pytest.mark.django_db
class TestPublishEventNode:
    """Exercise the workflow engine's new ``publish_event`` node directly.

    Eager Celery + an in-memory mock for the CeleryEventPublisher gives a
    clean assertion that filters work + the right shared-kernel event is
    constructed without spinning the full dispatcher → run lifecycle.
    """

    def _build_run(
        self,
        *,
        task_id: str,
        workspace_id: str,
        previous_column_id: str,
        new_column_id: str,
        source_type: str = "ai.book_balance.budget_overrun",
    ):
        from types import SimpleNamespace

        return SimpleNamespace(
            id="run-1",
            workflow=SimpleNamespace(id="workflow-1"),
            target_id=workspace_id,
            target_type="group",
            trigger_type="task_moved_column",
            trigger_payload={
                "task_id": task_id,
                "workspace_id": workspace_id,
                "user_id": "00000000-0000-0000-0000-000000000aaa",
                "previous_column_id": previous_column_id,
                "new_column_id": new_column_id,
                "task_source_type": source_type,
            },
        )

    def test_publishes_event_when_filters_pass(
        self, workspace_factory, team_factory
    ):
        from infrastructure.persistence.project.models import Column, Project
        from components.workflow.infrastructure.adapters.node_actions import (
            _execute_publish_event,
        )

        workspace = workspace_factory()
        owner = workspace.workspace_owner
        team = team_factory(workspace=workspace, created_by=owner, members=[owner])
        project = Project.objects.create(
            workspace=workspace, team=team, title="Demo", created_by=owner,
        )
        suggested = Column.objects.create(
            workspace=workspace, team=team, project=project,
            title="Suggested", order=0, created_by=owner,
        )
        accepted = Column.objects.create(
            workspace=workspace, team=team, project=project,
            title="Accepted", order=1, created_by=owner,
        )

        run = self._build_run(
            task_id="00000000-0000-0000-0000-000000000aaa",
            workspace_id=str(workspace.id),
            previous_column_id=str(suggested.id),
            new_column_id=str(accepted.id),
        )

        with patch(
            "components.shared_kernel.infrastructure.adapters.celery_event_publisher."
            "CeleryEventPublisher.publish"
        ) as publish_mock:
            result = _execute_publish_event(
                run=run,
                node={"id": "publish", "type": "publish_event"},
                config={
                    "event_type": "task_accepted_from_board",
                    "filters": {
                        "task_source_type_prefix": "ai.",
                        "new_column_title": "Accepted",
                    },
                },
            )

        assert result["status"] == "delivered"
        assert result["event_type"] == "task_accepted_from_board"
        publish_mock.assert_called_once()
        published_event = publish_mock.call_args.args[0]
        assert published_event.source_type == "ai.book_balance.budget_overrun"

    def test_skips_when_source_type_prefix_does_not_match(
        self, workspace_factory, team_factory
    ):
        from infrastructure.persistence.project.models import Column, Project
        from components.workflow.infrastructure.adapters.node_actions import (
            _execute_publish_event,
        )

        workspace = workspace_factory()
        owner = workspace.workspace_owner
        team = team_factory(workspace=workspace, created_by=owner, members=[owner])
        project = Project.objects.create(
            workspace=workspace, team=team, title="Demo", created_by=owner,
        )
        accepted = Column.objects.create(
            workspace=workspace, team=team, project=project,
            title="Accepted", order=0, created_by=owner,
        )

        run = self._build_run(
            task_id="00000000-0000-0000-0000-000000000aaa",
            workspace_id=str(workspace.id),
            previous_column_id="00000000-0000-0000-0000-000000000bbb",
            new_column_id=str(accepted.id),
            source_type="manual",  # NOT ai.*
        )

        with patch(
            "components.shared_kernel.infrastructure.adapters.celery_event_publisher."
            "CeleryEventPublisher.publish"
        ) as publish_mock:
            result = _execute_publish_event(
                run=run,
                node={"id": "publish", "type": "publish_event"},
                config={
                    "event_type": "task_accepted_from_board",
                    "filters": {
                        "task_source_type_prefix": "ai.",
                        "new_column_title": "Accepted",
                    },
                },
            )

        assert result["status"] == "skipped"
        publish_mock.assert_not_called()

    def test_skips_when_new_column_title_does_not_match(
        self, workspace_factory, team_factory
    ):
        from infrastructure.persistence.project.models import Column, Project
        from components.workflow.infrastructure.adapters.node_actions import (
            _execute_publish_event,
        )

        workspace = workspace_factory()
        owner = workspace.workspace_owner
        team = team_factory(workspace=workspace, created_by=owner, members=[owner])
        project = Project.objects.create(
            workspace=workspace, team=team, title="Demo", created_by=owner,
        )
        review = Column.objects.create(
            workspace=workspace, team=team, project=project,
            title="Under Review", order=0, created_by=owner,
        )

        run = self._build_run(
            task_id="00000000-0000-0000-0000-000000000aaa",
            workspace_id=str(workspace.id),
            previous_column_id="00000000-0000-0000-0000-000000000bbb",
            new_column_id=str(review.id),
            source_type="ai.book_balance.budget_overrun",
        )

        with patch(
            "components.shared_kernel.infrastructure.adapters.celery_event_publisher."
            "CeleryEventPublisher.publish"
        ) as publish_mock:
            result = _execute_publish_event(
                run=run,
                node={"id": "publish", "type": "publish_event"},
                config={
                    "event_type": "task_accepted_from_board",
                    "filters": {
                        "task_source_type_prefix": "ai.",
                        "new_column_title": "Accepted",
                    },
                },
            )

        assert result["status"] == "skipped"
        publish_mock.assert_not_called()


@pytest.mark.django_db
class TestEnsureAiFindingsWorkflowBinding:
    def test_creates_workflow_and_binding_when_template_seeded(
        self, workspace_factory
    ):
        from infrastructure.persistence.workspaces.workflows.models import (
            Workflow,
            WorkflowBinding,
            WorkflowTemplate,
        )
        from components.workflow.application.facades.ai_findings_workflow_facade import (
            ensure_ai_findings_workflow_binding,
        )

        # Pre-seed the template the facade depends on.
        WorkflowTemplate.objects.create(
            id="ai-findings-accepted",
            label="AI Findings Accepted",
            category="agents",
            version="1",
            description="…",
            is_system=True,
            default_graph={"nodes": [], "edges": []},
        )

        workspace = workspace_factory()
        binding = ensure_ai_findings_workflow_binding(workspace)

        assert binding is not None
        assert binding.source_type == "task"
        assert binding.trigger_type == "task_moved_column"
        assert binding.is_active is True

        workflow = Workflow.objects.get(workspace=workspace, template_id="ai-findings-accepted")
        assert workflow.status == Workflow.Status.PUBLISHED
        assert WorkflowBinding.objects.filter(workflow=workflow).count() == 1

    def test_idempotent_on_re_run(self, workspace_factory):
        from infrastructure.persistence.workspaces.workflows.models import (
            Workflow,
            WorkflowBinding,
            WorkflowTemplate,
        )
        from components.workflow.application.facades.ai_findings_workflow_facade import (
            ensure_ai_findings_workflow_binding,
        )

        WorkflowTemplate.objects.create(
            id="ai-findings-accepted",
            label="AI Findings Accepted",
            category="agents",
            version="1",
            description="…",
            is_system=True,
            default_graph={"nodes": [], "edges": []},
        )

        workspace = workspace_factory()
        first = ensure_ai_findings_workflow_binding(workspace)
        second = ensure_ai_findings_workflow_binding(workspace)

        assert first.id == second.id
        assert Workflow.objects.filter(workspace=workspace).count() == 1
        assert WorkflowBinding.objects.filter(
            workflow__workspace=workspace
        ).count() == 1

    def test_returns_none_when_template_not_seeded(self, workspace_factory):
        from components.workflow.application.facades.ai_findings_workflow_facade import (
            ensure_ai_findings_workflow_binding,
        )

        workspace = workspace_factory()
        result = ensure_ai_findings_workflow_binding(workspace)
        # Fresh DB: no template, no binding. Bootstrap can retry later.
        assert result is None
