import pytest

from components.agents.domain.value_objects.plan_schemas import AssigneeType, Priority, TaskSpec
from components.agents.infrastructure.gateways.deep.kanban_sync_service import upsert_task_from_spec
from infrastructure.persistence.ai.agents.models import Agent
from infrastructure.persistence.project.models import Column


@pytest.mark.django_db(databases=["default"])
def test_upsert_task_persists_description_and_agent_assignee(user_factory, workspace_factory, team_factory):
    owner = user_factory()
    workspace = workspace_factory(owner=owner)
    team = team_factory(workspace=workspace, created_by=owner, members=[owner])
    agent = Agent.objects.create(agent_type="task_agent", user=owner, workspace=workspace)

    spec = TaskSpec(
        title="Deep task",
        description="Do the thing with context",
        priority=Priority.high,
        workspace_id=str(workspace.id),
        team_id=str(team.id),
        assignee_id=str(agent.agent_id),
        assignee_type=AssigneeType.agent,
    )

    task = upsert_task_from_spec(spec, created_by_id=str(owner.id))

    assert task.assigned_to.filter(id=owner.id).exists()
    assert task.comments.filter(comment="Do the thing with context").exists()


@pytest.mark.django_db(databases=["default"])
def test_upsert_seeds_default_board_columns(user_factory, workspace_factory, team_factory):
    """F4 (QA report 2026-08-16): the ensure-columns step must actually run.

    The fork imported ``infrastructure.persistence.workspaces.utils`` — a
    module that does not exist here — inside a swallowed ``except``, so a deep
    sync onto a bare team only ever created the single column the task landed
    in. The step now goes through the workspace facade and must leave the
    canonical board behind.
    """
    owner = user_factory()
    workspace = workspace_factory(owner=owner)
    team = team_factory(workspace=workspace, created_by=owner, members=[owner])
    assert not Column.objects.filter(team=team).exists()

    task = upsert_task_from_spec(
        TaskSpec(title="Seed check", workspace_id=str(workspace.id), team_id=str(team.id)),
        created_by_id=str(owner.id),
    )

    titles = set(Column.objects.filter(team=team, project__isnull=True).values_list("title", flat=True))
    assert {"Backlog", "Todo", "In Progress", "Testing", "Complete", "Canceled"} <= titles
    # The task resolves onto the SEEDED Backlog, not a duplicate.
    assert task.column.title == "Backlog"
    assert Column.objects.filter(team=team, project__isnull=True, title="Backlog").count() == 1
