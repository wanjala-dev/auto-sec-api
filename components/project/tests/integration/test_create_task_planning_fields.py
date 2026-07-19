"""Integration test: ``CreateTaskCommand.due_date`` / ``.priority``.

The task-creation wizard captures planning fields (due date, priority,
description, assignees) at creation time — previously settable only
post-creation via PATCH, which is why the create modal offered nothing
beyond a title. This test proves:

* passing ``due_date`` (ISO date or datetime) and ``priority`` persists both;
* omitting them keeps the model defaults (MEDIUM priority, no due date);
* invalid values raise ``TaskValidationError`` (→ 400, not 500).
"""
from __future__ import annotations

import pytest

from components.project.application.ports.create_task_port import CreateTaskCommand
from components.project.application.providers.project_provider import ProjectProvider
from components.project.domain.errors import TaskValidationError


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
class TestCreateTaskPlanningFields:
    def test_persists_due_date_priority_and_description(self, workspace_factory):
        from infrastructure.persistence.project.models import Task

        workspace = workspace_factory()
        _b, column, user_id = _board(workspace)

        use_case = ProjectProvider.build_create_task_use_case()
        result = use_case.execute(
            command=CreateTaskCommand(
                title="Planned task",
                column_id=str(column.id),
                user_id=user_id,
                workspace_id=str(workspace.id),
                description="Ship the wizard",
                due_date="2026-08-15",
                priority="High",
            )
        )

        task = Task.objects.get(id=result.task_id)
        assert task.priority == Task.Priority.HIGH
        assert task.due_date is not None
        assert task.due_date.date().isoformat() == "2026-08-15"
        assert task.description == "Ship the wizard"
        assert result.priority == Task.Priority.HIGH
        assert result.due_date is not None

    def test_defaults_when_omitted(self, workspace_factory):
        from infrastructure.persistence.project.models import Task

        workspace = workspace_factory()
        _b, column, user_id = _board(workspace)

        use_case = ProjectProvider.build_create_task_use_case()
        result = use_case.execute(
            command=CreateTaskCommand(
                title="Bare task",
                column_id=str(column.id),
                user_id=user_id,
                workspace_id=str(workspace.id),
            )
        )

        task = Task.objects.get(id=result.task_id)
        assert task.priority == Task.Priority.MEDIUM
        assert task.due_date is None

    def test_invalid_priority_rejected(self, workspace_factory):
        workspace = workspace_factory()
        _b, column, user_id = _board(workspace)

        use_case = ProjectProvider.build_create_task_use_case()
        with pytest.raises(TaskValidationError):
            use_case.execute(
                command=CreateTaskCommand(
                    title="Bad priority",
                    column_id=str(column.id),
                    user_id=user_id,
                    workspace_id=str(workspace.id),
                    priority="maximum",
                )
            )

    def test_invalid_due_date_rejected(self, workspace_factory):
        workspace = workspace_factory()
        _b, column, user_id = _board(workspace)

        use_case = ProjectProvider.build_create_task_use_case()
        with pytest.raises(TaskValidationError):
            use_case.execute(
                command=CreateTaskCommand(
                    title="Bad due date",
                    column_id=str(column.id),
                    user_id=user_id,
                    workspace_id=str(workspace.id),
                    due_date="not-a-date",
                )
            )
