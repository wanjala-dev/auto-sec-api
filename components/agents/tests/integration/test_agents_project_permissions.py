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


@pytest.mark.django_db
def test_create_project_with_plan_allows_workspace_member(monkeypatch, workspace_factory, user_factory):
    owner = user_factory()
    workspace = workspace_factory(owner=owner)
    agent = _DummyAgent(workspace_id=str(workspace.id), user_id=str(owner.id))

    def _stubbed_plan(*_args, **_kwargs):
        return {
            "status": "completed",
            "result": {
                "project_id": "proj-1",
                "task_ids": ["task-1"],
                "transaction_ids": ["txn-1"],
                "estimated_total": "123.45",
                "summary": "Drafted plan",
            },
        }

    monkeypatch.setattr(
        "components.agents.infrastructure.services.deep_service.plan_and_create_project",
        _stubbed_plan,
    )

    response = project_tools.create_project_with_plan(
        agent,
        {"name": "Digging a well", "confirm": True},
    )

    assert "Project Planned and Created" in response


@pytest.mark.django_db
def test_create_project_with_plan_denies_non_member(monkeypatch, workspace_factory, user_factory):
    owner = user_factory()
    workspace = workspace_factory(owner=owner)
    outsider = user_factory()
    agent = _DummyAgent(workspace_id=str(workspace.id), user_id=str(outsider.id))

    monkeypatch.setattr(
        "components.agents.infrastructure.services.deep_service.plan_and_create_project",
        lambda *_args, **_kwargs: {"status": "completed", "result": {}},
    )

    response = project_tools.create_project_with_plan(
        agent,
        {"name": "Unauthorized plan", "confirm": True},
    )

    assert "permission denied" in response.lower()
