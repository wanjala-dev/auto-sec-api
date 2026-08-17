"""Workspace isolation for the P1 status seam (tenancy invariant 8).

P1 exposes no API reads, but it does add one read/write seam: the sync
bridge resolves and lazily seeds ``WorkflowStatus`` rows by (team, workspace).
A missing workspace filter there IS a cross-tenant leak — a task in workspace
A silently pointing at workspace B's status row. These tests prove the seam
is scoped: same-named lanes in two workspaces resolve to two disjoint status
sets, and nothing a tenant does creates or mutates rows in another tenant.
"""

from __future__ import annotations

import pytest

from infrastructure.persistence.project.models import Column, Task, WorkflowStatus

pytestmark = [pytest.mark.integration, pytest.mark.django_db]


def _board(workspace_factory, team_factory):
    workspace = workspace_factory()
    owner = workspace.workspace_owner
    team = team_factory(workspace=workspace, created_by=owner, members=[owner])
    return workspace, owner, team


def test_same_named_lanes_in_two_workspaces_resolve_to_disjoint_statuses(workspace_factory, team_factory):
    workspace_a, owner_a, team_a = _board(workspace_factory, team_factory)
    workspace_b, owner_b, team_b = _board(workspace_factory, team_factory)

    column_a = Column.objects.create(
        team=team_a, workspace=workspace_a, project=None, title="Todo", order=2, created_by=owner_a
    )
    column_b = Column.objects.create(
        team=team_b, workspace=workspace_b, project=None, title="Todo", order=2, created_by=owner_b
    )

    column_a.refresh_from_db()
    column_b.refresh_from_db()
    assert column_a.workflow_status_id != column_b.workflow_status_id
    assert column_a.workflow_status.workspace_id == workspace_a.id
    assert column_b.workflow_status.workspace_id == workspace_b.id


def test_task_mirror_never_points_across_the_workspace_boundary(workspace_factory, team_factory):
    workspace_a, owner_a, team_a = _board(workspace_factory, team_factory)
    workspace_b, owner_b, team_b = _board(workspace_factory, team_factory)
    column_a = Column.objects.create(
        team=team_a, workspace=workspace_a, project=None, title="In Progress", order=3, created_by=owner_a
    )
    Column.objects.create(
        team=team_b, workspace=workspace_b, project=None, title="In Progress", order=3, created_by=owner_b
    )

    task = Task.objects.create(workspace=workspace_a, team=team_a, column=column_a, title="mine", created_by=owner_a)

    task.refresh_from_db()
    assert task.workflow_status.workspace_id == workspace_a.id
    assert task.workflow_status.team_id == team_a.id


def test_lazy_seeding_for_one_tenant_creates_nothing_for_another(workspace_factory, team_factory):
    workspace_a, owner_a, team_a = _board(workspace_factory, team_factory)
    workspace_b, _owner_b, _team_b = _board(workspace_factory, team_factory)
    before_b = WorkflowStatus.objects.filter(workspace=workspace_b).count()

    Column.objects.create(
        team=team_a, workspace=workspace_a, project=None, title="Weird Lane", order=9, created_by=owner_a
    )

    assert WorkflowStatus.objects.filter(workspace=workspace_b).count() == before_b
    assert not WorkflowStatus.objects.filter(workspace=workspace_b, name="Weird Lane").exists()


def test_backfill_scopes_statuses_and_views_per_team_and_workspace(workspace_factory, team_factory):
    import importlib

    from django.apps import apps as django_apps

    from infrastructure.persistence.project.models import BoardView

    _migration = importlib.import_module(
        "infrastructure.persistence.project.migrations.0008_backfill_workflow_statuses_and_board_views"
    )

    class _SchemaEditorStub:
        class connection:
            alias = "default"

    workspace_a, owner_a, team_a = _board(workspace_factory, team_factory)
    workspace_b, owner_b, team_b = _board(workspace_factory, team_factory)
    Column.objects.create(team=team_a, workspace=workspace_a, project=None, title="Todo", order=2, created_by=owner_a)
    Column.objects.create(team=team_b, workspace=workspace_b, project=None, title="Todo", order=2, created_by=owner_b)
    WorkflowStatus.objects.all().delete()
    BoardView.objects.all().delete()

    _migration.backfill_workflow_statuses_and_board_views(django_apps, _SchemaEditorStub())

    for workspace, team in ((workspace_a, team_a), (workspace_b, team_b)):
        statuses = WorkflowStatus.objects.filter(team=team)
        assert statuses.count() == 6
        assert all(s.workspace_id == workspace.id for s in statuses)
        view = BoardView.objects.get(team=team, slug="board")
        assert view.workspace_id == workspace.id
