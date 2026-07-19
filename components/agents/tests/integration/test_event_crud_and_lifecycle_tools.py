"""DB-backed tests for fundraising_agent Event CRUD + lifecycle tools (PR-B4).

The audit found ``infrastructure/persistence/sponsorship/events`` was a
complete model with zero agent surface — chat couldn't ask "what events
do we have?" let alone create one. PR-B4 wires the existing
``EventService`` (already used by the events API controller and the
events lifecycle endpoint shipped in PR #59) into the fundraising
agent.

These tests exercise the actual ``EventService`` against the real DB
so a regression in the underlying service surfaces here too. Lifecycle
state transitions are tested with the canonical happy-path sequence
(DRAFT → SCHEDULED → LIVE → PAUSED → LIVE → ENDED) plus an illegal-
transition rejection.
"""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from django.utils import timezone

from components.agents.infrastructure.adapters.langchain.tools import (
    fundraising_agent as fundraising_tools,
)


def _make_agent(workspace_id, user=None):
    agent = MagicMock()
    agent.workspace_id = str(workspace_id)
    agent.user_id = str(user.id) if user else None
    agent.config = {}
    return agent


@pytest.fixture
def event_setup(workspace_factory, user_factory):
    """Workspace + user with one Event already created."""
    from infrastructure.persistence.sponsorship.events.models import Event

    user = user_factory()
    workspace = workspace_factory(owner=user)
    event = Event.objects.create(
        workspace=workspace,
        owner=user,
        title="Annual gala",
        summary="A summary",
        goal_amount=Decimal("10000.00"),
    )
    return {
        "user": user,
        "workspace": workspace,
        "event": event,
        "agent": _make_agent(workspace.id, user),
    }


# ── list_events ────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestListEvents:
    def test_returns_helpful_when_empty(self, workspace_factory):
        ws = workspace_factory()
        result = fundraising_tools.list_events(_make_agent(ws.id), {})
        assert "No events" in result

    def test_lists_workspace_events_only(
        self, workspace_factory, user_factory
    ):
        from infrastructure.persistence.sponsorship.events.models import Event

        u = user_factory()
        ws_a = workspace_factory(owner=u)
        ws_b = workspace_factory(owner=u)
        Event.objects.create(workspace=ws_a, owner=u, title="In A")
        Event.objects.create(workspace=ws_b, owner=u, title="In B")
        result = fundraising_tools.list_events(_make_agent(ws_a.id, u), {})
        assert "In A" in result
        assert "In B" not in result

    def test_filters_by_status(self, workspace_factory, user_factory):
        from infrastructure.persistence.sponsorship.events.models import Event

        u = user_factory()
        ws = workspace_factory(owner=u)
        Event.objects.create(workspace=ws, owner=u, title="Planning one")
        Event.objects.create(
            workspace=ws,
            owner=u,
            title="Active one",
            status=Event.Status.ACTIVE,
        )
        result = fundraising_tools.list_events(
            _make_agent(ws.id, u), {"status": "active"}
        )
        assert "Active one" in result
        assert "Planning one" not in result

    def test_rejects_unknown_status(self, event_setup):
        result = fundraising_tools.list_events(
            event_setup["agent"], {"status": "fortnightly"}
        )
        assert "Invalid status" in result


# ── get_event_info ─────────────────────────────────────────────────────


@pytest.mark.django_db
class TestGetEventInfo:
    def test_fetches_by_id(self, event_setup):
        result = fundraising_tools.get_event_info(
            event_setup["agent"],
            {"event_id": str(event_setup["event"].id)},
        )
        assert event_setup["event"].title in result
        assert "10000.00" in result

    def test_rejects_missing_id(self, event_setup):
        result = fundraising_tools.get_event_info(event_setup["agent"], {})
        assert "event_id is required" in result

    def test_rejects_invalid_uuid(self, event_setup):
        result = fundraising_tools.get_event_info(
            event_setup["agent"], {"event_id": "not-a-uuid"}
        )
        assert "valid UUID" in result

    def test_rejects_unknown_event(self, event_setup):
        result = fundraising_tools.get_event_info(
            event_setup["agent"],
            {"event_id": "00000000-0000-0000-0000-000000000000"},
        )
        assert "not found" in result

    def test_rejects_cross_workspace(
        self, workspace_factory, user_factory
    ):
        from infrastructure.persistence.sponsorship.events.models import Event

        u = user_factory()
        ws_a = workspace_factory(owner=u)
        ws_b = workspace_factory(owner=u)
        event_in_b = Event.objects.create(
            workspace=ws_b, owner=u, title="Other workspace"
        )
        result = fundraising_tools.get_event_info(
            _make_agent(ws_a.id, u), {"event_id": str(event_in_b.id)}
        )
        assert "not found" in result


# ── create_event ───────────────────────────────────────────────────────


@pytest.mark.django_db
class TestCreateEvent:
    def test_creates_minimum_event(self, workspace_factory, user_factory):
        from infrastructure.persistence.sponsorship.events.models import Event

        u = user_factory()
        ws = workspace_factory(owner=u)
        result = fundraising_tools.create_event(
            _make_agent(ws.id, u), {"title": "New event"}
        )
        assert "Created event" in result
        assert Event.objects.filter(workspace=ws, title="New event").exists()

    def test_rejects_missing_title(self, workspace_factory, user_factory):
        u = user_factory()
        ws = workspace_factory(owner=u)
        result = fundraising_tools.create_event(_make_agent(ws.id, u), {})
        assert "title is required" in result

    def test_rejects_missing_user(self, workspace_factory):
        ws = workspace_factory()
        agent = _make_agent(ws.id)  # No user.
        result = fundraising_tools.create_event(agent, {"title": "X"})
        assert "user context" in result.lower()

    def test_rejects_invalid_status(self, workspace_factory, user_factory):
        u = user_factory()
        ws = workspace_factory(owner=u)
        result = fundraising_tools.create_event(
            _make_agent(ws.id, u), {"title": "X", "status": "scheduled"}
        )
        assert "Invalid status" in result

    def test_rejects_invalid_goal_amount(self, workspace_factory, user_factory):
        u = user_factory()
        ws = workspace_factory(owner=u)
        result = fundraising_tools.create_event(
            _make_agent(ws.id, u),
            {"title": "X", "goal_amount": "free"},
        )
        assert "Invalid goal_amount" in result

    def test_creates_with_full_details(self, workspace_factory, user_factory):
        from infrastructure.persistence.sponsorship.events.models import Event

        u = user_factory()
        ws = workspace_factory(owner=u)
        result = fundraising_tools.create_event(
            _make_agent(ws.id, u),
            {
                "title": "Big gala",
                "summary": "Annual fundraiser",
                "location_type": "in_person",
                "location_name": "City hall",
                "city": "Nairobi",
                "country": "KE",
                "start_date": "2026-09-15T18:00:00",
                "end_date": "2026-09-15T22:00:00",
                "goal_amount": "25000.50",
                "registration_url": "https://example.com/register",
            },
        )
        assert "Created event" in result
        e = Event.objects.get(workspace=ws, title="Big gala")
        assert e.location_name == "City hall"
        assert e.goal_amount == Decimal("25000.50")
        assert e.registration_url == "https://example.com/register"


# ── update_event ───────────────────────────────────────────────────────


@pytest.mark.django_db
class TestUpdateEvent:
    def test_updates_only_passed_fields(self, event_setup):
        original_title = event_setup["event"].title
        result = fundraising_tools.update_event(
            event_setup["agent"],
            {"event_id": str(event_setup["event"].id), "summary": "A new summary"},
        )
        assert "Updated event" in result
        event_setup["event"].refresh_from_db()
        # Title untouched.
        assert event_setup["event"].title == original_title
        # Summary updated.
        assert event_setup["event"].summary == "A new summary"

    def test_rejects_missing_event_id(self, event_setup):
        result = fundraising_tools.update_event(
            event_setup["agent"], {"title": "Renamed"}
        )
        assert "event_id is required" in result

    def test_rejects_invalid_uuid(self, event_setup):
        result = fundraising_tools.update_event(
            event_setup["agent"], {"event_id": "not-a-uuid", "title": "x"}
        )
        assert "valid UUID" in result


# ── transition_event_lifecycle ─────────────────────────────────────────


@pytest.mark.django_db
class TestTransitionEventLifecycle:
    def test_canonical_lifecycle_path(self, event_setup):
        from infrastructure.persistence.sponsorship.events.models import Event

        # DRAFT → SCHEDULED
        future = (timezone.now() + timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%S")
        result = fundraising_tools.transition_event_lifecycle(
            event_setup["agent"],
            {
                "event_id": str(event_setup["event"].id),
                "transition": "schedule",
                "scheduled_at": future,
            },
        )
        assert "Applied transition 'schedule'" in result
        event_setup["event"].refresh_from_db()
        assert event_setup["event"].lifecycle_state == Event.LifecycleState.SCHEDULED

        # SCHEDULED → LIVE
        result = fundraising_tools.transition_event_lifecycle(
            event_setup["agent"],
            {"event_id": str(event_setup["event"].id), "transition": "go_live"},
        )
        assert "Applied transition 'go_live'" in result
        event_setup["event"].refresh_from_db()
        assert event_setup["event"].lifecycle_state == Event.LifecycleState.LIVE

        # LIVE → PAUSED
        result = fundraising_tools.transition_event_lifecycle(
            event_setup["agent"],
            {"event_id": str(event_setup["event"].id), "transition": "pause"},
        )
        event_setup["event"].refresh_from_db()
        assert event_setup["event"].lifecycle_state == Event.LifecycleState.PAUSED

        # PAUSED → LIVE
        result = fundraising_tools.transition_event_lifecycle(
            event_setup["agent"],
            {"event_id": str(event_setup["event"].id), "transition": "resume"},
        )
        event_setup["event"].refresh_from_db()
        assert event_setup["event"].lifecycle_state == Event.LifecycleState.LIVE

        # LIVE → ENDED
        result = fundraising_tools.transition_event_lifecycle(
            event_setup["agent"],
            {"event_id": str(event_setup["event"].id), "transition": "end"},
        )
        event_setup["event"].refresh_from_db()
        assert event_setup["event"].lifecycle_state == Event.LifecycleState.ENDED

    def test_schedule_requires_scheduled_at(self, event_setup):
        result = fundraising_tools.transition_event_lifecycle(
            event_setup["agent"],
            {"event_id": str(event_setup["event"].id), "transition": "schedule"},
        )
        assert "scheduled_at is required" in result

    def test_rejects_unknown_transition(self, event_setup):
        result = fundraising_tools.transition_event_lifecycle(
            event_setup["agent"],
            {"event_id": str(event_setup["event"].id), "transition": "summon"},
        )
        assert "Invalid transition" in result

    def test_state_machine_rejects_illegal_jump(self, event_setup):
        """The underlying service must reject illegal transitions
        (e.g. ``pause`` from ``DRAFT``). Tool surfaces it as an error
        string instead of a Python traceback.
        """
        result = fundraising_tools.transition_event_lifecycle(
            event_setup["agent"],
            {"event_id": str(event_setup["event"].id), "transition": "pause"},
        )
        # The exact message comes from the events domain — we just
        # verify the tool didn't crash and produced an error string.
        assert "Error" in result or "invalid" in result.lower() or "cannot" in result.lower()


# ── delete_event ───────────────────────────────────────────────────────


@pytest.mark.django_db
class TestDeleteEvent:
    def test_deletes_event(self, event_setup):
        result = fundraising_tools.delete_event(
            event_setup["agent"], {"event_id": str(event_setup["event"].id)}
        )
        assert "Deleted event" in result

    def test_rejects_missing_id(self, event_setup):
        result = fundraising_tools.delete_event(event_setup["agent"], {})
        assert "event_id is required" in result
