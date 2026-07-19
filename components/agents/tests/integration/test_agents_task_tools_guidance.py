from types import SimpleNamespace

import pytest

from components.agents.infrastructure.adapters.langchain.tools import task_agent as task_tools


@pytest.mark.django_db
def test_get_user_tasks_rejects_task_title(workspace_factory, user_factory):
    user = user_factory()
    workspace = workspace_factory(owner=user)
    agent = SimpleNamespace(workspace_id=str(workspace.id), user_id=str(user.id), config={})

    response = task_tools.get_user_tasks(agent, "website redesign task")

    assert "get_task_assignment" in response
    assert "tasks for a user" in response.lower()


@pytest.mark.django_db
def test_get_task_assignment_returns_not_found(workspace_factory, user_factory):
    user = user_factory()
    workspace = workspace_factory(owner=user)
    agent = SimpleNamespace(workspace_id=str(workspace.id), user_id=str(user.id), config={})

    response = task_tools.get_task_assignment(agent, title="website redesign task")

    assert "not found" in response.lower()


@pytest.mark.django_db
def test_get_task_assignment_parses_question_prompt(workspace_factory, user_factory):
    user = user_factory()
    workspace = workspace_factory(owner=user)
    agent = SimpleNamespace(workspace_id=str(workspace.id), user_id=str(user.id), config={})

    response = task_tools.get_task_assignment(agent, "Who is assigned to the website redesign task?")

    assert "not found" in response.lower()
