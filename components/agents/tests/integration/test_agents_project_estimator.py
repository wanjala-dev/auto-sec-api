"""Tests for the project estimator tool."""
from __future__ import annotations

import json

import pytest

from components.agents.infrastructure.adapters.langchain.tools import project_estimator
from infrastructure.persistence.budget.categories.models import Category


class _FakeLLM:
    def __init__(self, content: str):
        self._content = content

    def invoke(self, _messages):
        return type("LLMResponse", (), {"content": self._content})()


@pytest.mark.django_db
def test_estimator_maps_existing_categories(workspace_factory, user_factory, monkeypatch):
    user = user_factory()
    workspace = workspace_factory(owner=user)
    Category.objects.create(workspace=workspace, user=user, name="Transport", slug="transport")

    items = [
        {"label": f"Item {idx}", "amount": 100 + idx, "category_name": "Transport"}
        for idx in range(6)
    ]
    content = json.dumps({"items": items})
    # ``LLMFactory`` is imported lazily inside
    # ``estimate_project_items_for_workspace``; patch its real module
    # path so the substitution survives the deferred import.
    monkeypatch.setattr(
        "components.knowledge.infrastructure.factories.llms.factory.LLMFactory.get_llm",
        lambda *_a, **_kw: _FakeLLM(content),
    )

    lines = project_estimator.estimate_project_items_for_workspace(
        workspace_id=str(workspace.id),
        user_id=str(user.id),
        project_title="Test Project",
        goal="Test goal",
        max_items=6,
    )

    assert len(lines) == 6
    assert all(line.metadata.get("category_name") == "Transport" for line in lines)


@pytest.mark.django_db
def test_estimator_creates_missing_category(workspace_factory, user_factory, monkeypatch):
    user = user_factory()
    workspace = workspace_factory(owner=user)

    items = [
        {"label": f"Item {idx}", "amount": 50 + idx, "category_name": "New Category"}
        for idx in range(6)
    ]
    content = json.dumps({"items": items})
    # ``LLMFactory`` is imported lazily inside
    # ``estimate_project_items_for_workspace``; patch its real module
    # path so the substitution survives the deferred import.
    monkeypatch.setattr(
        "components.knowledge.infrastructure.factories.llms.factory.LLMFactory.get_llm",
        lambda *_a, **_kw: _FakeLLM(content),
    )

    lines = project_estimator.estimate_project_items_for_workspace(
        workspace_id=str(workspace.id),
        user_id=str(user.id),
        project_title="Test Project",
        goal="Test goal",
        max_items=6,
    )

    assert len(lines) == 6
    assert Category.objects.filter(workspace=workspace, name="New Category").exists()
    assert all(line.metadata.get("category_name") == "New Category" for line in lines)
