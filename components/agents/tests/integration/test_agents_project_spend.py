"""Tests for the project-resolution helpers on ProjectAgent.

The nonprofit ``get_project_spend`` tool reported *budget spend* (project
estimate/actual transactions) for a named project. Budgeting was stripped from
the autosec fork, so the tool — and any notion of project "spend" — no longer
exists. What survives is the project-resolution behaviour those tests exercised:
looking a project up by name and listing available projects when it is missing
(``get_project_info``), and parsing a project name out of free text
(``_extract_project_name``). These tests cover that real fork behaviour.
"""

from types import SimpleNamespace

import pytest

from components.agents.infrastructure.adapters.langchain.tools import project_agent
from infrastructure.persistence.project.models import Project


@pytest.mark.django_db
def test_get_project_info_lists_projects_when_missing(
    user_factory,
    workspace_factory,
    team_factory,
):
    owner = user_factory()
    workspace = workspace_factory(owner=owner)
    team = team_factory(workspace=workspace, created_by=owner, members=[owner])
    Project.objects.create(workspace=workspace, team=team, title="Project Sunrise", created_by=owner)

    agent = SimpleNamespace(workspace_id=str(workspace.id), user_id=str(owner.id), config={})

    result = project_agent.get_project_info(agent, "Unknown")

    assert "Project 'Unknown' not found." in result
    assert "Project Sunrise" in result


@pytest.mark.django_db
def test_get_project_info_returns_surviving_fields_when_found(
    user_factory,
    workspace_factory,
    team_factory,
):
    """Happy path: a found project renders cleanly.

    Regression guard for the fork drift where ``get_project_info`` read
    ``project.budget`` (stripped with budgeting) and ``project.updated_at``
    (never existed on Project) — both would break whenever a project was
    actually found. The tool must report only surviving Project fields.
    """
    owner = user_factory()
    workspace = workspace_factory(owner=owner)
    team = team_factory(workspace=workspace, created_by=owner, members=[owner])
    Project.objects.create(
        workspace=workspace,
        team=team,
        title="Project Sunrise",
        description="Restore log ingestion",
        created_by=owner,
        lead=owner,
    )

    agent = SimpleNamespace(workspace_id=str(workspace.id), user_id=str(owner.id), config={})

    result = project_agent.get_project_info(agent, "Sunrise")

    assert "Project Information:" in result
    assert "Name: Project Sunrise" in result
    assert "Restore log ingestion" in result
    assert "Team:" in result
    assert "Tasks: 0" in result
    assert "Milestones: 0" in result
    # The removed/nonexistent fields must not surface, and nothing errored.
    assert "Budget" not in result
    assert "Error retrieving project info" not in result


@pytest.mark.django_db
def test_extract_project_name_parses_project_from_text(
    user_factory,
    workspace_factory,
    team_factory,
):
    owner = user_factory()
    workspace = workspace_factory(owner=owner)
    team = team_factory(workspace=workspace, created_by=owner, members=[owner])
    Project.objects.create(workspace=workspace, team=team, title="Project Sunrise", created_by=owner)

    name = project_agent._extract_project_name("How much have we spent on Project Sunrise this quarter?")

    assert name == "Sunrise"
    # The parsed name resolves to the seeded project (same lookup get_project_info uses).
    assert Project.objects.filter(title__icontains=name, workspace_id=str(workspace.id)).exists()
