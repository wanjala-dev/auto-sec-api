"""Tests for project spend tool."""
from types import SimpleNamespace

import pytest

from components.agents.infrastructure.adapters.langchain.tools import project_agent
from infrastructure.persistence.project.models import Project


@pytest.mark.django_db
def test_get_project_spend_lists_projects_when_missing(
    user_factory,
    workspace_factory,
    team_factory,
):
    owner = user_factory()
    workspace = workspace_factory(owner=owner)
    team = team_factory(workspace=workspace, created_by=owner, members=[owner])
    Project.objects.create(workspace=workspace, team=team, title="Project Sunrise", created_by=owner)

    agent = SimpleNamespace(workspace_id=str(workspace.id), user_id=str(owner.id), config={})

    result = project_agent.get_project_spend(agent, {"project": "Unknown"})

    assert "Project 'Unknown' not found." in result
    assert "Project Sunrise" in result


@pytest.mark.django_db
def test_get_project_spend_parses_project_from_text(
    user_factory,
    workspace_factory,
    team_factory,
):
    owner = user_factory()
    workspace = workspace_factory(owner=owner)
    team = team_factory(workspace=workspace, created_by=owner, members=[owner])
    Project.objects.create(workspace=workspace, team=team, title="Project Sunrise", created_by=owner)

    agent = SimpleNamespace(workspace_id=str(workspace.id), user_id=str(owner.id), config={})

    result = project_agent.get_project_spend(
        agent,
        {"text": "How much have we spent on Project Sunrise this quarter?"},
    )

    assert "Project spend for Project Sunrise" in result
