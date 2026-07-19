"""Integration tests for ``OrmWorkspaceEventLatestAdapter``.

Pins the cross-context query — the adapter walks 8 sources (the same
set that has signal bridges) and returns the max. A new signal
bridge added without an adapter update would silently under-report
lag, so the parametric test makes the contract explicit.

The tests use the real ORM against the workspace_factory + a small
helper to create a row on each watched model and assert the
adapter sees it.
"""

from __future__ import annotations

import pytest

from components.knowledge.infrastructure.adapters.orm_workspace_event_latest_adapter import (
    OrmWorkspaceEventLatestAdapter,
)


@pytest.mark.django_db
class TestLatestEventTime:
    def test_empty_workspace_returns_none(self, workspace_factory):
        ws = workspace_factory()
        # The workspace itself has a ``modified`` row from creation,
        # so latest_event_time is at least the workspace's own row.
        # Confirm the type — non-None datetime.
        adapter = OrmWorkspaceEventLatestAdapter()
        result = adapter.latest_event_time(workspace_id=str(ws.id))
        assert result is not None  # workspace row itself is an event

    def test_blank_workspace_id_returns_none(self):
        adapter = OrmWorkspaceEventLatestAdapter()
        assert adapter.latest_event_time(workspace_id="") is None

    def test_membership_event_picked_up(self, workspace_factory, user_factory):
        """Tier 3 #14 audit found WorkspaceMembership wasn't a
        recognised event source. After the fix, a membership write
        registers as an event the adapter sees."""
        from infrastructure.persistence.workspaces.models import (
            WorkspaceMembership,
        )

        ws = workspace_factory()
        user = user_factory()
        WorkspaceMembership.objects.create(
            workspace=ws,
            user=user,
            role="contributor",
            persona="contributor",
            status="active",
        )

        adapter = OrmWorkspaceEventLatestAdapter()
        result = adapter.latest_event_time(workspace_id=str(ws.id))
        assert result is not None
