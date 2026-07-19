"""Integration test: ``task_assigned`` workflow trigger.

Phase 4 of the Agents-as-Teammates migration completes the task
lifecycle event family:

    AssignUsersToTaskView.patch → M2M add → on_commit →
    ``emit_workflow_event(trigger_type="task_assigned")``

This test pins emission per newly-assigned user, idempotency against
re-assignment, and that the assignee_id is carried on the payload so
downstream workflow bindings (e.g. "auto-comment when @sarah is
assigned") can route on it.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
from rest_framework.test import APIClient


def _captured_emits(emit_mock):
    return [call.kwargs for call in emit_mock.call_args_list]


@pytest.mark.django_db
class TestAssignUsersEmitsTaskAssigned:
    def test_assigning_new_user_emits_task_assigned(
        self, workspace_factory, team_factory, user_factory,
        django_capture_on_commit_callbacks,
    ):
        from infrastructure.persistence.project.models import Column, Project, Task

        workspace = workspace_factory()
        owner = workspace.workspace_owner
        assignee = user_factory()
        team = team_factory(
            workspace=workspace, created_by=owner, members=[owner, assignee],
        )
        project = Project.objects.create(
            workspace=workspace, team=team, title="Demo", created_by=owner,
        )
        column = Column.objects.create(
            workspace=workspace, team=team, project=project,
            title="Suggested", order=0, created_by=owner,
        )
        task = Task.objects.create(
            workspace=workspace, team=team, project=project,
            column=column, created_by=owner,
            title="AI finding", source_type="ai.book_balance.budget_overrun",
        )

        client = APIClient()
        client.force_authenticate(user=owner)

        # The emit is deferred via transaction.on_commit; capture + execute
        # the callbacks so it fires while the patch is still active.
        with patch(
            "components.workflow.infrastructure.adapters.dispatcher."
            "emit_workflow_event"
        ) as emit_mock:
            with django_capture_on_commit_callbacks(execute=True):
                response = client.patch(
                    f"/project/tasks/{task.id}/assign/",
                    data={"user_ids": [str(assignee.id)]},
                    format="json",
                )

        assert response.status_code == 200, response.content

        emits = _captured_emits(emit_mock)
        assigned = [e for e in emits if e.get("trigger_type") == "task_assigned"]
        assert len(assigned) == 1
        payload = assigned[0]["payload"]
        assert payload["task_id"] == str(task.id)
        assert payload["assignee_id"] == str(assignee.id)
        assert payload["task_source_type"] == "ai.book_balance.budget_overrun"
        assert payload["target_type"] == "group"
        assert payload["target_id"] == str(workspace.id)
        assert assigned[0]["idempotency_key"] == (
            f"task_assigned:{task.id}:{assignee.id}"
        )

    def test_reassigning_existing_user_does_not_emit(
        self, workspace_factory, team_factory, user_factory
    ):
        from infrastructure.persistence.project.models import Column, Project, Task

        workspace = workspace_factory()
        owner = workspace.workspace_owner
        assignee = user_factory()
        team = team_factory(
            workspace=workspace, created_by=owner, members=[owner, assignee],
        )
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
        task.assigned_to.add(assignee)

        client = APIClient()
        client.force_authenticate(user=owner)

        with patch(
            "components.workflow.infrastructure.adapters.dispatcher."
            "emit_workflow_event"
        ) as emit_mock:
            response = client.patch(
                f"/project/tasks/{task.id}/assign/",
                data={"user_ids": [str(assignee.id)]},
                format="json",
            )

        assert response.status_code == 200
        emits = _captured_emits(emit_mock)
        assigned = [e for e in emits if e.get("trigger_type") == "task_assigned"]
        assert assigned == []

    def test_assigning_multiple_users_emits_one_per_new_assignee(
        self, workspace_factory, team_factory, user_factory,
        django_capture_on_commit_callbacks,
    ):
        from infrastructure.persistence.project.models import Column, Project, Task

        workspace = workspace_factory()
        owner = workspace.workspace_owner
        sarah = user_factory()
        bob = user_factory()
        team = team_factory(
            workspace=workspace, created_by=owner,
            members=[owner, sarah, bob],
        )
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

        client = APIClient()
        client.force_authenticate(user=owner)

        # The emit is deferred via transaction.on_commit; capture + execute
        # the callbacks so both fire while the patch is still active.
        with patch(
            "components.workflow.infrastructure.adapters.dispatcher."
            "emit_workflow_event"
        ) as emit_mock:
            with django_capture_on_commit_callbacks(execute=True):
                response = client.patch(
                    f"/project/tasks/{task.id}/assign/",
                    data={"user_ids": [str(sarah.id), str(bob.id)]},
                    format="json",
                )

        assert response.status_code == 200
        emits = _captured_emits(emit_mock)
        assigned = [e for e in emits if e.get("trigger_type") == "task_assigned"]
        assert len(assigned) == 2
        assignee_ids = {e["payload"]["assignee_id"] for e in assigned}
        assert assignee_ids == {str(sarah.id), str(bob.id)}
