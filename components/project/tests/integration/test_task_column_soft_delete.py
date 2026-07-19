"""Integration — Task + Column soft-delete adapters (recycle bin).

Mirrors ``test_project_soft_delete.py``. Asserts:
  1. Task soft_delete archives (status=ARCHIVED), remembers the prior status
     in metadata, and restore puts the status back losslessly.
  2. Column soft_delete flips ``is_deleted`` and archives the column's live
     tasks with a stamp; restore un-archives exactly the stamped tasks and
     leaves independently archived tasks archived.
  3. hard_delete removes the rows (recycle-bin purge).
  4. The provider registry exposes 'task' and 'column' so the recycle-bin
     controller accepts trash requests for both.
  5. An archived task drops out of the team board list query.
"""
from __future__ import annotations

import pytest

from components.project.infrastructure.adapters.column_soft_delete_adapter import (
    ARCHIVED_BY_COLUMN_KEY,
    ColumnSoftDeleteAdapter,
)
from components.project.infrastructure.adapters.task_soft_delete_adapter import (
    PRE_TRASH_STATUS_KEY,
    TaskSoftDeleteAdapter,
)
from components.project.infrastructure.repositories.project_repository import ProjectRepository
from components.recycle_bin.application.providers.recycle_bin_provider import (
    get_recycle_bin_service,
)
from infrastructure.persistence.project.models import Column, Task

pytestmark = pytest.mark.django_db


def _column(workspace, team, user, *, title="To Do"):
    return Column.objects.create(
        workspace=workspace, team=team, title=title, created_by=user
    )


def _task(workspace, team, user, column=None, *, title="QA Task", status=Task.TODO):
    return Task.objects.create(
        workspace=workspace,
        team=team,
        column=column,
        title=title,
        status=status,
        created_by=user,
    )


class TestTaskSoftDeleteAdapter:
    def test_soft_delete_archives_and_snapshots(
        self, workspace_factory, team_factory, user_factory
    ) -> None:
        owner = user_factory()
        workspace = workspace_factory(owner=owner)
        team = team_factory(workspace=workspace, created_by=owner)
        column = _column(workspace, team, owner)
        task = _task(workspace, team, owner, column, title="Alpha", status=Task.DONE)

        snapshot = TaskSoftDeleteAdapter().soft_delete(str(task.pk))

        task.refresh_from_db()
        assert task.status == Task.ARCHIVED
        assert task.metadata[PRE_TRASH_STATUS_KEY] == Task.DONE
        assert snapshot["id"] == str(task.pk)
        assert snapshot["title"] == "Alpha"
        assert snapshot["status"] == Task.DONE
        assert snapshot["column_id"] == str(column.pk)

    def test_restore_puts_prior_status_back(
        self, workspace_factory, team_factory, user_factory
    ) -> None:
        owner = user_factory()
        workspace = workspace_factory(owner=owner)
        team = team_factory(workspace=workspace, created_by=owner)
        task = _task(workspace, team, owner, status=Task.DONE)

        adapter = TaskSoftDeleteAdapter()
        adapter.soft_delete(str(task.pk))
        adapter.restore(str(task.pk))

        task.refresh_from_db()
        assert task.status == Task.DONE
        assert PRE_TRASH_STATUS_KEY not in (task.metadata or {})

    def test_hard_delete_removes_row(
        self, workspace_factory, team_factory, user_factory
    ) -> None:
        owner = user_factory()
        workspace = workspace_factory(owner=owner)
        team = team_factory(workspace=workspace, created_by=owner)
        task = _task(workspace, team, owner)

        TaskSoftDeleteAdapter().hard_delete(str(task.pk))

        assert not Task.objects.filter(pk=task.pk).exists()

    def test_archived_task_drops_off_board_list(
        self, workspace_factory, team_factory, user_factory
    ) -> None:
        owner = user_factory()
        workspace = workspace_factory(owner=owner)
        team = team_factory(workspace=workspace, created_by=owner)
        keep = _task(workspace, team, owner, title="Keep")
        trash = _task(workspace, team, owner, title="Trash")

        TaskSoftDeleteAdapter().soft_delete(str(trash.pk))

        listed = ProjectRepository().list_tasks_for_team_and_workspace(
            str(team.id), str(workspace.id)
        )
        listed_ids = {t.pk for t in listed}
        assert keep.pk in listed_ids
        assert trash.pk not in listed_ids


class TestColumnSoftDeleteAdapter:
    def test_soft_delete_flags_column_and_archives_its_tasks(
        self, workspace_factory, team_factory, user_factory
    ) -> None:
        owner = user_factory()
        workspace = workspace_factory(owner=owner)
        team = team_factory(workspace=workspace, created_by=owner)
        column = _column(workspace, team, owner, title="Doomed")
        live = _task(workspace, team, owner, column, title="Live", status=Task.DONE)
        already_archived = _task(
            workspace, team, owner, column, title="Old", status=Task.ARCHIVED
        )

        snapshot = ColumnSoftDeleteAdapter().soft_delete(str(column.pk))

        column.refresh_from_db()
        live.refresh_from_db()
        already_archived.refresh_from_db()
        assert column.is_deleted is True
        assert snapshot["title"] == "Doomed"
        assert snapshot["archived_task_count"] == 1
        assert live.status == Task.ARCHIVED
        assert live.metadata[ARCHIVED_BY_COLUMN_KEY] == str(column.pk)
        assert live.metadata[PRE_TRASH_STATUS_KEY] == Task.DONE
        # Untouched: it was archived before the column trash.
        assert ARCHIVED_BY_COLUMN_KEY not in (already_archived.metadata or {})

    def test_restore_unarchives_only_stamped_tasks(
        self, workspace_factory, team_factory, user_factory
    ) -> None:
        owner = user_factory()
        workspace = workspace_factory(owner=owner)
        team = team_factory(workspace=workspace, created_by=owner)
        column = _column(workspace, team, owner)
        live = _task(workspace, team, owner, column, title="Live", status=Task.DONE)
        already_archived = _task(
            workspace, team, owner, column, title="Old", status=Task.ARCHIVED
        )

        adapter = ColumnSoftDeleteAdapter()
        adapter.soft_delete(str(column.pk))
        adapter.restore(str(column.pk))

        column.refresh_from_db()
        live.refresh_from_db()
        already_archived.refresh_from_db()
        assert column.is_deleted is False
        assert live.status == Task.DONE
        assert ARCHIVED_BY_COLUMN_KEY not in (live.metadata or {})
        assert already_archived.status == Task.ARCHIVED

    def test_hard_delete_removes_column_but_keeps_tasks(
        self, workspace_factory, team_factory, user_factory
    ) -> None:
        owner = user_factory()
        workspace = workspace_factory(owner=owner)
        team = team_factory(workspace=workspace, created_by=owner)
        column = _column(workspace, team, owner)
        task = _task(workspace, team, owner, column)

        adapter = ColumnSoftDeleteAdapter()
        adapter.soft_delete(str(column.pk))
        adapter.hard_delete(str(column.pk))

        assert not Column.objects.filter(pk=column.pk).exists()
        task.refresh_from_db()
        assert task.column_id is None  # FK is SET_NULL


class TestRegistryExposure:
    def test_task_and_column_are_registered_entity_types(self) -> None:
        supported = get_recycle_bin_service().provider.supported_types()
        assert "task" in supported
        assert "column" in supported
