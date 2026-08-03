"""Tests for ProjectAgent permission helpers."""

from __future__ import annotations

import pytest

from components.agents.infrastructure.adapters.langchain.tools import project_agent as project_tools


class _DummyAgent:
    def __init__(self, *, workspace_id: str, user_id: str):
        self.workspace_id = workspace_id
        self.user_id = user_id
        self.config = {}


@pytest.mark.django_db
def test_check_project_permissions_uses_workspace_owner_when_user_id_invalid(workspace_factory, user_factory):
    owner = user_factory()
    workspace = workspace_factory(owner=owner)
    agent = _DummyAgent(workspace_id=str(workspace.id), user_id=str(owner.id))

    result = project_tools.check_project_permissions(
        agent,
        {"workspace_id": str(workspace.id), "user_id": "Project Agent"},
    )

    assert "workspace owner" in result.lower()


# The nonprofit ``create_project_with_plan`` tool (which fanned an LLM planner out
# into budget *estimate transactions* via ``deep_service.plan_and_create_project``)
# was intentionally removed in the autosec fork — there is no budgeting context to
# plan against. Project creation is now the direct, budget-free ``create_project``
# tool (``project_agent.py``). These tests exercise the SAME permission gate the
# planning tool used (``_has_action_access(..., "project:write")``) against the real
# fork tool: a workspace member may create a project, a non-member is denied.


@pytest.mark.django_db
def test_create_project_allows_workspace_member(workspace_factory, user_factory, team_factory):
    owner = user_factory()
    workspace = workspace_factory(owner=owner)
    team = team_factory(workspace=workspace, created_by=owner, members=[owner])
    agent = _DummyAgent(workspace_id=str(workspace.id), user_id=str(owner.id))

    response = project_tools.create_project(
        agent,
        {"name": "Digging a well", "team_id": str(team.id), "confirm": True},
    )

    assert "Project created" in response
    assert "Digging a well" in response


@pytest.mark.django_db
def test_create_project_denies_non_member(workspace_factory, user_factory, team_factory):
    owner = user_factory()
    workspace = workspace_factory(owner=owner)
    team = team_factory(workspace=workspace, created_by=owner, members=[owner])
    outsider = user_factory()
    agent = _DummyAgent(workspace_id=str(workspace.id), user_id=str(outsider.id))

    response = project_tools.create_project(
        agent,
        {"name": "Unauthorized project", "team_id": str(team.id), "confirm": True},
    )

    assert "permission denied" in response.lower()
