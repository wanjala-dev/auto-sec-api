"""A model switch must leave a mark (ADR 0032 D7.4).

``AIModelChangeEvent`` was defined, indexed, and READ by
``ai_analytics_repository`` — and a repo-wide grep found no producer. Its own
docstring named ``OrmWorkspaceAIConfigAdapter.save`` as the writer; that method
simply never wrote one. So ``model_changes[]`` on the quality overview was
permanently empty, and "did the switch help?" — the entire point of letting an
admin change models — was unanswerable by construction.

Also pinned here: a re-save with no model change must NOT emit an event. A
series littered with markers for saves that changed a temperature would read as
switch churn, which is worse than no annotation.
"""

from __future__ import annotations

import pytest
from django.core.management import call_command

from components.agents.domain.value_objects.workspace_ai_config import WorkspaceAIConfig
from components.agents.infrastructure.adapters.workspace_ai_config_adapter import (
    OrmWorkspaceAIConfigAdapter,
)
from infrastructure.persistence.ai.aggregations.models import AIModelChangeEvent
from infrastructure.persistence.ai.models import AITeammateProfile

URL = "/ai/agents/ai-config/update"


@pytest.fixture
def roles(db):
    call_command("seed_workspace_roles")


def _profile(workspace):
    """The AI config lives in ``AITeammateProfile.config`` (legacy shape)."""
    return AITeammateProfile.objects.get_or_create(
        workspace=workspace,
        defaults={"user": workspace.workspace_owner},
    )[0]


def _events(workspace):
    return list(AIModelChangeEvent.objects.filter(workspace=workspace).order_by("field"))


@pytest.mark.django_db
class TestTheAdapterWritesTheEvent:
    def test_changing_the_preferred_model_records_an_event(self, workspace_factory):
        workspace = workspace_factory()
        _profile(workspace)
        adapter = OrmWorkspaceAIConfigAdapter()
        adapter.save(str(workspace.id), WorkspaceAIConfig(preferred_model="gpt-4o-mini"))

        adapter.save(
            str(workspace.id),
            WorkspaceAIConfig(preferred_model="claude-sonnet-4-20250514"),
            changed_by_id=str(workspace.workspace_owner.id),
        )

        events = [e for e in _events(workspace) if e.field == "preferred_model"]
        # First save is itself a change (default -> gpt-4o-mini is a no-op, so
        # exactly one event: the real switch).
        assert len(events) == 1
        assert events[0].old_value == "gpt-4o-mini"
        assert events[0].new_value == "claude-sonnet-4-20250514"
        assert str(events[0].changed_by_id) == str(workspace.workspace_owner.id)

    def test_changing_the_fallback_model_records_its_own_event(self, workspace_factory):
        workspace = workspace_factory()
        _profile(workspace)
        adapter = OrmWorkspaceAIConfigAdapter()
        adapter.save(str(workspace.id), WorkspaceAIConfig())

        adapter.save(str(workspace.id), WorkspaceAIConfig(fallback_model="gpt-4o"))

        events = [e for e in _events(workspace) if e.field == "fallback_model"]
        assert len(events) == 1
        assert events[0].new_value == "gpt-4o"
        assert events[0].changed_by_id is None  # unattributed, not invented

    def test_saving_an_unchanged_config_writes_nothing(self, workspace_factory):
        workspace = workspace_factory()
        _profile(workspace)
        adapter = OrmWorkspaceAIConfigAdapter()
        adapter.save(str(workspace.id), WorkspaceAIConfig())
        before = AIModelChangeEvent.objects.filter(workspace=workspace).count()

        adapter.save(str(workspace.id), WorkspaceAIConfig())

        assert AIModelChangeEvent.objects.filter(workspace=workspace).count() == before

    def test_changing_a_non_model_field_writes_nothing(self, workspace_factory):
        """Bumping a temperature is not a model switch."""
        workspace = workspace_factory()
        _profile(workspace)
        adapter = OrmWorkspaceAIConfigAdapter()
        adapter.save(str(workspace.id), WorkspaceAIConfig(temperature=0.3))
        before = AIModelChangeEvent.objects.filter(workspace=workspace).count()

        adapter.save(str(workspace.id), WorkspaceAIConfig(temperature=0.9))

        assert AIModelChangeEvent.objects.filter(workspace=workspace).count() == before

    def test_both_models_moving_records_both(self, workspace_factory):
        workspace = workspace_factory()
        _profile(workspace)
        adapter = OrmWorkspaceAIConfigAdapter()
        adapter.save(str(workspace.id), WorkspaceAIConfig())
        AIModelChangeEvent.objects.filter(workspace=workspace).delete()

        adapter.save(
            str(workspace.id),
            WorkspaceAIConfig(preferred_model="gpt-4o", fallback_model="gpt-4o-mini"),
        )

        assert {e.field for e in _events(workspace)} == {"preferred_model", "fallback_model"}


@pytest.mark.django_db
class TestTheEventReachesTheDashboard:
    def test_a_switch_annotates_the_quality_overview(
        self, roles, api_client, workspace_factory, user_factory, team_factory
    ):
        workspace = workspace_factory()
        _profile(workspace)
        adapter = OrmWorkspaceAIConfigAdapter()
        adapter.save(str(workspace.id), WorkspaceAIConfig(preferred_model="gpt-4o-mini"))
        adapter.save(str(workspace.id), WorkspaceAIConfig(preferred_model="gpt-4o"))

        analyst = user_factory()
        team_factory(workspace=workspace, members=[analyst])
        api_client.force_authenticate(analyst)
        body = api_client.get(
            "/ai/agents/runs/analytics/overview/",
            {"workspace_id": str(workspace.id), "days": 30},
        ).json()

        changes = [c for c in body["model_changes"] if c["field"] == "preferred_model"]
        assert changes, "the switch annotation is what makes 'did it help?' answerable"
        assert changes[-1]["new_value"] == "gpt-4o"

    def test_another_workspaces_switches_never_appear(
        self, roles, api_client, workspace_factory, user_factory, team_factory
    ):
        mine = workspace_factory()
        theirs = workspace_factory()
        _profile(theirs)
        adapter = OrmWorkspaceAIConfigAdapter()
        adapter.save(str(theirs.id), WorkspaceAIConfig(preferred_model="secret-model"))

        analyst = user_factory()
        team_factory(workspace=mine, members=[analyst])
        api_client.force_authenticate(analyst)
        body = api_client.get(
            "/ai/agents/runs/analytics/overview/",
            {"workspace_id": str(mine.id), "days": 30},
        ).json()

        assert body["model_changes"] == []


@pytest.mark.django_db
class TestTheSwitchCostIsAvailableBeforeTheSwitch:
    """ADR 0032 D7.3 — the cost is a precondition of the decision, not a receipt."""

    URL = "/ai/agents/ai-config/switch-cost/"

    def test_it_states_the_cost_for_a_candidate_model(self, roles, api_client, user_factory):
        api_client.force_authenticate(user_factory())

        response = api_client.get(self.URL, {"from": "gpt-3.5-turbo", "to": "gpt-4o"})

        assert response.status_code == 200, response.data
        body = response.json()
        assert body["current_model"] == "gpt-3.5-turbo"
        assert body["candidate_model"] == "gpt-4o"
        assert body["is_noop"] is False
        assert body["headline"]
        assert "do not transfer between models" in body["detail"]
        assert "never accumulates" in body["anti_thrash_note"]

    def test_the_candidate_model_is_required(self, roles, api_client, user_factory):
        api_client.force_authenticate(user_factory())
        assert api_client.get(self.URL, {"from": "gpt-4o"}).status_code == 400

    def test_anonymous_is_denied(self, api_client):
        assert api_client.get(self.URL, {"to": "gpt-4o"}).status_code in (401, 403)

    def test_switching_to_the_same_model_costs_nothing(self, roles, api_client, user_factory):
        api_client.force_authenticate(user_factory())

        body = api_client.get(self.URL, {"from": "gpt-4o", "to": "gpt-4o"}).json()

        assert body["is_noop"] is True
        assert body["downgraded"] == []
