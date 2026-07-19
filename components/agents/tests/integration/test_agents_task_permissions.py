"""Tests for task tool permission handling."""
from types import SimpleNamespace

import pytest

from components.agents.infrastructure.adapters.langchain.tools import task_agent
from infrastructure.persistence.project.models import Task


@pytest.mark.django_db
def test_create_task_allows_workspace_follower(user_factory, workspace_factory, team_factory):
    owner = user_factory()
    follower = user_factory()
    workspace = workspace_factory(owner=owner)
    workspace.followers.add(follower)
    team_factory(workspace=workspace)

    agent = SimpleNamespace(workspace_id=str(workspace.id), user_id=str(follower.id), config={})

    # ``task_agent.create_task`` takes ``(agent, params)``; pass the
    # task fields as a dict instead of separate kwargs.
    result = task_agent.create_task(agent, {"title": "Draft annual report"})

    assert result.startswith("Successfully created task:")
    task = Task.objects.get(workspace_id=workspace.id, title="Draft annual report")
    assert str(task.created_by_id) == str(follower.id)


@pytest.mark.django_db
def test_create_task_sets_backlog_column_when_requested(user_factory, workspace_factory, team_factory):
    from infrastructure.persistence.project.models import Column

    owner = user_factory()
    workspace = workspace_factory(owner=owner)
    team = team_factory(workspace=workspace)
    team.members.add(owner)
    # The team-board bootstrap helper was removed during the agents/Hex
    # refactor; with no project context the workspace-level Backlog
    # column must exist for the lookup-by-title fallback to match.
    Column.objects.create(
        workspace=workspace, team=team, project=None, title="Backlog"
    )

    agent = SimpleNamespace(workspace_id=str(workspace.id), user_id=str(owner.id), config={})

    # ``task_agent.create_task`` takes ``(agent, params)``; pass the
    # request fields as a dict instead of separate kwargs.
    result = task_agent.create_task(
        agent, {"title": "Draft TikTok post", "column_title": "Backlog"}
    )

    assert result.startswith("Successfully created task:")
    task = Task.objects.get(workspace_id=workspace.id, title="Draft TikTok post")
    assert task.column is not None
    assert task.column.title == "Backlog"
    assert task.column.project_id is None
