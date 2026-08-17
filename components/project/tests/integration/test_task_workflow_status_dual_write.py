"""Dual-write: every column write also sets ``workflow_status`` (ADR 0030 P1).

The seam is ONE signal bridge
(``components/project/infrastructure/adapters/django_workflow_status_sync_bridge.py``)
registered from the project app's ``ready()`` — plus the single signal-less
bulk path (batch-move's ``bulk_update``), which carries the mirror explicitly
because Django fires no signals for ``bulk_update``.

These tests drive the REAL write paths (ORM create, the batch-move
repository, the specialist-move ``save(update_fields=...)`` shape,
``ensure_board_column``) — never by poking the field directly. Written before
the bridge existed and watched failing (bug-style, ``no-shortcuts.md``): the
``update_fields`` persistence test in particular pins the subtle failure a
naive pre_save-only bridge would reintroduce (Django does not persist fields
a pre_save receiver sets when the save named ``update_fields`` without them).
"""

from __future__ import annotations

import pytest

from components.project.domain.workflow_status_vocabulary import (
    CATEGORY_STARTED,
    CATEGORY_UNSTARTED,
)
from infrastructure.persistence.project.models import Column, Task

pytestmark = [pytest.mark.integration, pytest.mark.django_db]


def _board(workspace_factory, team_factory):
    workspace = workspace_factory()
    owner = workspace.workspace_owner
    team = team_factory(workspace=workspace, created_by=owner, members=[owner])
    return workspace, owner, team


def _column(workspace, owner, team, title, order):
    return Column.objects.create(
        team=team, workspace=workspace, project=None, title=title, order=order, created_by=owner
    )


class TestColumnCreationResolvesStatus:
    def test_new_canonical_column_gets_its_status(self, workspace_factory, team_factory):
        workspace, owner, team = _board(workspace_factory, team_factory)

        column = _column(workspace, owner, team, "Todo", 2)

        column.refresh_from_db()
        assert column.workflow_status is not None
        assert column.workflow_status.name == "Todo"
        assert column.workflow_status.category == CATEGORY_UNSTARTED
        assert column.workflow_status.team_id == team.id
        assert column.workflow_status.workspace_id == workspace.id

    def test_ensure_board_column_new_column_gets_status_via_title_mapping(self, workspace_factory, team_factory):
        """The lazy specialist lane ("Triage") maps onto In Progress —
        the SAME mapping the backfill uses, not a parallel one."""
        from components.agents.infrastructure.adapters.langchain.tools._finding_processing import (
            ensure_board_column,
        )

        workspace, owner, team = _board(workspace_factory, team_factory)

        column = ensure_board_column(team, workspace, owner, "Triage")

        column.refresh_from_db()
        assert column.workflow_status is not None
        assert column.workflow_status.name == "In Progress"
        assert column.workflow_status.category == CATEGORY_STARTED

    def test_unknown_title_creates_team_local_started_status(self, workspace_factory, team_factory, caplog):
        import logging

        workspace, owner, team = _board(workspace_factory, team_factory)

        with caplog.at_level(logging.WARNING):
            column = _column(workspace, owner, team, "Security Review", 9)

        column.refresh_from_db()
        assert column.workflow_status is not None
        assert column.workflow_status.name == "Security Review"
        assert column.workflow_status.category == CATEGORY_STARTED
        assert any("unmapped column" in record.message for record in caplog.records)


class TestTaskDualWrite:
    def test_creating_a_task_with_a_column_sets_workflow_status(self, workspace_factory, team_factory):
        workspace, owner, team = _board(workspace_factory, team_factory)
        todo = _column(workspace, owner, team, "Todo", 2)

        task = Task.objects.create(workspace=workspace, team=team, column=todo, title="do it", created_by=owner)

        task.refresh_from_db()
        assert task.workflow_status_id == todo.workflow_status_id
        assert task.workflow_status_id is not None

    def test_creating_a_task_without_a_column_leaves_status_null(self, workspace_factory, team_factory):
        workspace, owner, team = _board(workspace_factory, team_factory)

        task = Task.objects.create(workspace=workspace, team=team, column=None, title="floating", created_by=owner)

        task.refresh_from_db()
        assert task.workflow_status_id is None

    def test_batch_move_resyncs_workflow_status(self, workspace_factory, team_factory):
        """Through the REAL batch-move repository — the one write path with no
        signals (``bulk_update``), so it must carry the mirror itself."""
        from components.project.application.ports.batch_move_tasks_port import (
            BatchMoveTasksCommand,
            TaskMove,
        )
        from components.project.infrastructure.repositories.batch_move_tasks_repository import (
            OrmBatchMoveTasksRepository,
        )

        workspace, owner, team = _board(workspace_factory, team_factory)
        todo = _column(workspace, owner, team, "Todo", 2)
        in_progress = _column(workspace, owner, team, "In Progress", 3)
        task = Task.objects.create(workspace=workspace, team=team, column=todo, title="move me", created_by=owner)

        OrmBatchMoveTasksRepository().batch_move_tasks(
            command=BatchMoveTasksCommand(
                user_id=str(owner.id),
                moves=[TaskMove(task_id=str(task.id), column_id=str(in_progress.id), order=0)],
            )
        )

        task.refresh_from_db()
        assert task.column_id == in_progress.id
        assert task.workflow_status_id == in_progress.workflow_status_id
        assert task.workflow_status.name == "In Progress"

    def test_specialist_shape_partial_save_persists_workflow_status(self, workspace_factory, team_factory):
        """The specialist move saves ``update_fields=["metadata", "updated_at",
        "column"]`` (``_finding_processing.py``). A pre_save assignment alone is
        silently DROPPED by Django for fields not named in ``update_fields`` —
        this test pins that the bridge persists the mirror anyway."""
        workspace, owner, team = _board(workspace_factory, team_factory)
        suggested = _column(workspace, owner, team, "Suggested", 0)
        triage = _column(workspace, owner, team, "Triage", 1)
        task = Task.objects.create(workspace=workspace, team=team, column=suggested, title="finding", created_by=owner)

        task.metadata = {"triage": {"status": "triaged"}}
        task.column = triage
        task.save(update_fields=["metadata", "updated_at", "column"])

        task.refresh_from_db()
        assert task.column_id == triage.id
        assert task.workflow_status_id == triage.workflow_status_id
        assert task.workflow_status.name == "In Progress"

    def test_move_task_to_board_shape_partial_save_persists_workflow_status(self, workspace_factory, team_factory):
        """``MoveTaskToBoardView``'s repository shape:
        ``save(update_fields=["team", "project", "column", "order", "updated_at"])``."""
        workspace, owner, team = _board(workspace_factory, team_factory)
        todo = _column(workspace, owner, team, "Todo", 2)
        complete = _column(workspace, owner, team, "Complete", 5)
        task = Task.objects.create(workspace=workspace, team=team, column=todo, title="ship it", created_by=owner)

        task.column = complete
        task.order = 3
        task.save(update_fields=["team", "project", "column", "order", "updated_at"])

        task.refresh_from_db()
        assert task.workflow_status_id is not None
        assert task.workflow_status_id == complete.workflow_status_id

    def test_clearing_the_column_clears_workflow_status(self, workspace_factory, team_factory):
        workspace, owner, team = _board(workspace_factory, team_factory)
        todo = _column(workspace, owner, team, "Todo", 2)
        task = Task.objects.create(workspace=workspace, team=team, column=todo, title="detach me", created_by=owner)
        assert Task.objects.get(pk=task.pk).workflow_status_id is not None

        task.column = None
        task.save()

        task.refresh_from_db()
        assert task.workflow_status_id is None

    def test_null_mirror_heals_on_any_save(self, workspace_factory, team_factory):
        """A pre-backfill-shaped row (column set, mirror NULL) is healed by its
        next save even when that save does not touch the column."""
        workspace, owner, team = _board(workspace_factory, team_factory)
        todo = _column(workspace, owner, team, "Todo", 2)
        task = Task.objects.create(workspace=workspace, team=team, column=todo, title="stale", created_by=owner)
        # Simulate the pre-backfill state without firing signals.
        Task.objects.filter(pk=task.pk).update(workflow_status=None)

        stale = Task.objects.get(pk=task.pk)
        stale.title = "renamed"
        stale.save(update_fields=["title", "updated_at"])

        stale.refresh_from_db()
        assert stale.workflow_status_id is not None
        assert stale.workflow_status_id == todo.workflow_status_id

    def test_status_untouched_save_does_not_query_or_change_the_mirror(self, workspace_factory, team_factory):
        """A save that neither touches the column nor lacks the mirror leaves
        workflow_status exactly as it was."""
        workspace, owner, team = _board(workspace_factory, team_factory)
        todo = _column(workspace, owner, team, "Todo", 2)
        task = Task.objects.create(workspace=workspace, team=team, column=todo, title="steady", created_by=owner)
        expected = Task.objects.get(pk=task.pk).workflow_status_id
        assert expected is not None

        fresh = Task.objects.get(pk=task.pk)
        fresh.title = "still steady"
        fresh.save(update_fields=["title", "updated_at"])

        fresh.refresh_from_db()
        assert fresh.workflow_status_id == expected
