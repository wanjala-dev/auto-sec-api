"""Integration test: ``GET /ai/findings/?workspace_id=X&...`` endpoint.

Phase 5 of the Agents-as-Teammates migration. The canonical read
surface for every AI finding — replaces the deleted ``/ai/actions/``
endpoint. Returns Tasks created by specialist handlers and the
detector cycle, scoped to the workspace's AI agent team board.
"""
from __future__ import annotations

import pytest
from django.urls import reverse

from components.agents.application.handlers.budget_specialist_handler import (
    handle_book_balance_findings_detected,
)
from components.agents.application.handlers.budget_variance_specialist_handler import (
    handle_budget_variance_findings_detected,
)
from components.budgeting.domain.events.book_balance_findings_detected_event import (
    BookBalanceFindingsDetected,
)
from components.budgeting.domain.events.budget_variance_findings_detected_event import (
    BudgetVarianceFindingsDetected,
)


def _book_balance_event(workspace_id):
    return BookBalanceFindingsDetected(
        workspace_id=workspace_id,
        detector_key="book_balance_daily",
        window_start=__import__("datetime").date(2026, 5, 6),
        window_end=__import__("datetime").date(2026, 6, 5),
        period="2026-06-05",
        ai_headline="Books drift",
        ai_narrative="Detail",
        grouped_findings=(
            {
                "kind": "budget_overrun",
                "severity": "high",
                "title": "Education over",
                "summary": "S",
                "item_count": 1,
                "impact_score": 80,
                "items": [{"category": "Education"}],
            },
        ),
    )


def _variance_event(workspace_id):
    return BudgetVarianceFindingsDetected(
        workspace_id=workspace_id,
        detector_key="budget_variance_monthly",
        period="2026-06",
        findings=(
            {
                "category_id": 12,
                "category_name": "Education",
                "period": "2026-06",
                "current_spend": "450.00",
                "trailing_mean": "300.00",
                "variance_pct": "0.50",
                "impact_score": 50,
            },
        ),
    )


@pytest.mark.django_db
class TestAIFindingsViewSetList:
    # ``app_name = "agents"`` was restored in components/agents/api/urls.py
    # so all viewset reverses are namespaced under ``agents:``. The router
    # registers ``r'findings'`` with basename ``ai-findings`` → drf
    # auto-generates ``ai-findings-list`` / ``ai-findings-detail`` views.
    URL_NAME = "agents:ai-findings-list"

    def _seed_findings(self, workspace):
        handle_book_balance_findings_detected(_book_balance_event(workspace.id))
        handle_budget_variance_findings_detected(_variance_event(workspace.id))

    def test_returns_400_when_workspace_id_missing(self, api_client, user_factory):
        user = user_factory()
        api_client.force_authenticate(user=user)
        response = api_client.get(reverse(self.URL_NAME))
        assert response.status_code == 400

    def test_returns_empty_when_workspace_has_no_agent_team(
        self, api_client, user_factory, workspace_factory
    ):
        user = user_factory()
        workspace = workspace_factory(owner=user)
        api_client.force_authenticate(user=user)
        response = api_client.get(
            reverse(self.URL_NAME),
            {"workspace_id": str(workspace.id)},
        )
        assert response.status_code == 200
        assert response.data["results"] == []
        assert response.data["count"] == 0

    def test_lists_findings_for_workspace(
        self, api_client, user_factory, workspace_factory
    ):
        user = user_factory()
        workspace = workspace_factory(owner=user)
        self._seed_findings(workspace)
        api_client.force_authenticate(user=user)

        response = api_client.get(
            reverse(self.URL_NAME),
            {"workspace_id": str(workspace.id)},
        )
        assert response.status_code == 200
        results = response.data["results"]
        assert len(results) == 2
        source_types = {f["source_type"] for f in results}
        assert source_types == {
            "ai.book_balance.budget_overrun",
            "ai.budget_variance_detected",
        }
        # Every result carries agent attribution + detector context
        # via the new Task.metadata shape (Phase 5 dropped the nested
        # AIAction representation).
        for finding in results:
            assert "ai_action" not in finding
            assert finding["description"]
            metadata = finding["metadata"]
            assert metadata["agent_type"]
            assert metadata["detector"]
            assert metadata["severity"] in {"high", "medium", "low"}
            assert isinstance(metadata["impact_score"], int)
            assert metadata["action_type"]
            assert metadata["ai_headline"]
            assert metadata["ai_narrative"]

    def test_filters_by_source_type_exact(
        self, api_client, user_factory, workspace_factory
    ):
        user = user_factory()
        workspace = workspace_factory(owner=user)
        self._seed_findings(workspace)
        api_client.force_authenticate(user=user)

        response = api_client.get(
            reverse(self.URL_NAME),
            {
                "workspace_id": str(workspace.id),
                "source_type": "ai.budget_variance_detected",
            },
        )
        assert response.status_code == 200
        assert len(response.data["results"]) == 1
        assert response.data["results"][0]["source_type"] == (
            "ai.budget_variance_detected"
        )

    def test_filters_by_source_type_prefix(
        self, api_client, user_factory, workspace_factory
    ):
        user = user_factory()
        workspace = workspace_factory(owner=user)
        self._seed_findings(workspace)
        api_client.force_authenticate(user=user)

        response = api_client.get(
            reverse(self.URL_NAME),
            {
                "workspace_id": str(workspace.id),
                "source_type_prefix": "ai.book_balance",
            },
        )
        assert response.status_code == 200
        assert len(response.data["results"]) == 1
        assert response.data["results"][0]["source_type"].startswith(
            "ai.book_balance"
        )

    def test_filters_by_column_title(
        self, api_client, user_factory, workspace_factory
    ):
        user = user_factory()
        workspace = workspace_factory(owner=user)
        self._seed_findings(workspace)
        api_client.force_authenticate(user=user)

        # Specialist handlers persist into "Suggested" by default.
        response = api_client.get(
            reverse(self.URL_NAME),
            {
                "workspace_id": str(workspace.id),
                "column_title": "Suggested",
            },
        )
        assert response.status_code == 200
        assert len(response.data["results"]) == 2

        # Nothing in Accepted yet.
        response = api_client.get(
            reverse(self.URL_NAME),
            {
                "workspace_id": str(workspace.id),
                "column_title": "Accepted",
            },
        )
        assert response.status_code == 200
        assert response.data["results"] == []

    def test_excludes_tasks_not_on_agent_team(
        self,
        api_client,
        user_factory,
        workspace_factory,
        team_factory,
    ):
        """A human-created task on a non-agent team must NOT appear in
        the AI findings endpoint even if its source_type happens to be
        non-empty."""
        from infrastructure.persistence.project.models import Column, Project, Task

        user = user_factory()
        workspace = workspace_factory(owner=user)
        self._seed_findings(workspace)

        # Seed a human task on a regular (non-agent) team.
        human_team = team_factory(workspace=workspace, created_by=user, members=[user])
        project = Project.objects.create(
            workspace=workspace, team=human_team, title="Other", created_by=user,
        )
        column = Column.objects.create(
            workspace=workspace, team=human_team, project=project,
            title="Todo", order=0, created_by=user,
        )
        Task.objects.create(
            workspace=workspace, team=human_team, project=project,
            column=column, created_by=user, title="Human task",
            source_type="ai.book_balance.budget_overrun",  # spoofed
        )

        api_client.force_authenticate(user=user)
        response = api_client.get(
            reverse(self.URL_NAME),
            {"workspace_id": str(workspace.id)},
        )
        assert response.status_code == 200
        titles = {f["title"] for f in response.data["results"]}
        assert "Human task" not in titles
