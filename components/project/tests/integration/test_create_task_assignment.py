"""Integration test: ``CreateTaskCommand.assigned_to_ids`` (Phase 6b).

The sign-off materializer needs a created task to land pre-assigned to the
workspace owner. Phase 6b added an optional ``assigned_to_ids`` to
``CreateTaskCommand`` (default None → unchanged behaviour). This test
proves:

* passing ``assigned_to_ids`` adds those users to ``Task.assigned_to``;
* omitting it leaves ``assigned_to`` empty (existing callers unaffected).
"""
from __future__ import annotations

import pytest

from components.project.application.ports.create_task_port import CreateTaskCommand
from components.project.application.providers.project_provider import ProjectProvider


def _board(workspace):
    from components.agents.application.facades.ai_teammate_facade import (
        ensure_agents_board,
    )
    from components.agents.infrastructure.services.agents_board_service import (
        SUGGESTED,
    )

    board = ensure_agents_board(workspace)
    return board, board.column(SUGGESTED), str(board.team.created_by_id)


@pytest.mark.django_db
class TestCreateTaskAssignment:
    def test_assigns_users_when_ids_passed(self, workspace_factory):
        from infrastructure.persistence.project.models import Task

        workspace = workspace_factory()
        _b, column, ai_user_id = _board(workspace)
        owner_id = str(workspace.workspace_owner_id)

        use_case = ProjectProvider.build_create_task_use_case()
        result = use_case.execute(
            command=CreateTaskCommand(
                title="Assigned task",
                column_id=str(column.id),
                user_id=ai_user_id,
                workspace_id=str(workspace.id),
                source_type="ai.sign_off_pending",
                assigned_to_ids=[owner_id],
            )
        )

        task = Task.objects.get(id=result.task_id)
        assert owner_id in {str(u.id) for u in task.assigned_to.all()}

    def test_no_assignment_when_ids_omitted(self, workspace_factory):
        from infrastructure.persistence.project.models import Task

        workspace = workspace_factory()
        _b, column, ai_user_id = _board(workspace)

        use_case = ProjectProvider.build_create_task_use_case()
        result = use_case.execute(
            command=CreateTaskCommand(
                title="Unassigned task",
                column_id=str(column.id),
                user_id=ai_user_id,
                workspace_id=str(workspace.id),
            )
        )

        task = Task.objects.get(id=result.task_id)
        assert task.assigned_to.count() == 0
