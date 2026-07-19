"""Unit tests for BuildUserContextQuery active-workspace resolution.

Covers the bug where a followed-only org id persisted as the user's
active_workspace_id was reported as active in the summary, causing the
client to land on a non-member workspace and 403 on every gated call.
"""
from __future__ import annotations

from typing import Any

import pytest

from components.identity.application.queries.user_context_query import BuildUserContextQuery


class _FakeUserContextPort:
    """In-memory fake of UserContextQueryPort for pure-logic tests."""

    def __init__(
        self,
        *,
        accessible: list[str],
        active: str | None,
        personal: set[str] | None = None,
        teams: list[str] | None = None,
    ):
        self._accessible = accessible
        self._active = active
        self._personal = personal or set()
        self._teams = teams or []

    def get_accessible_workspace_ids(self, *, user_id: Any) -> list[str]:
        return list(self._accessible)

    def get_active_workspace_id(self, *, user_id: Any) -> str | None:
        return self._active

    def get_active_team_ids(self, *, user_id: Any) -> list[str]:
        return list(self._teams)

    def infer_workspace_kind(self, *, workspace_id: Any) -> str | None:
        if workspace_id is None:
            return None
        return "personal" if workspace_id in self._personal else "organization"

    def infer_workspace_role(self, *, user_id: Any, workspace_id: Any) -> str | None:
        return "owner" if workspace_id else None

    def is_workspace_owner(self, *, user_id: Any, workspace_id: Any) -> bool:
        return bool(workspace_id)

    def get_workspace_default_currency(self, *, workspace_id: Any) -> str | None:
        return "USD" if workspace_id else None


class TestActiveWorkspaceResolution:
    def test_member_active_workspace_is_preserved(self):
        port = _FakeUserContextPort(
            accessible=["member-a", "member-b"],
            active="member-b",
        )
        result = BuildUserContextQuery(port).execute(user_id="u1")

        assert result.active_workspace_id == "member-b"
        assert result.workspace_context.active_workspace_id == "member-b"

    def test_followed_only_active_falls_back_to_a_membership(self):
        # active points at an org NOT in the accessible (member) set → stale follower pointer.
        port = _FakeUserContextPort(
            accessible=["member-a", "member-b"],
            active="followed-org",
        )
        result = BuildUserContextQuery(port).execute(user_id="u1")

        assert result.active_workspace_id == "member-a"
        assert result.workspace_context.active_workspace_id == "member-a"

    def test_followed_only_active_with_no_memberships_resolves_to_none(self):
        port = _FakeUserContextPort(
            accessible=[],
            active="followed-org",
        )
        result = BuildUserContextQuery(port).execute(user_id="u1")

        assert result.active_workspace_id is None
        assert result.workspace_context.active_workspace_id is None

    def test_no_active_workspace_stays_none(self):
        port = _FakeUserContextPort(
            accessible=["member-a"],
            active=None,
        )
        result = BuildUserContextQuery(port).execute(user_id="u1")

        assert result.active_workspace_id is None

    def test_fallback_logs_warning(self, caplog):
        port = _FakeUserContextPort(
            accessible=["member-a"],
            active="followed-org",
        )
        import logging

        with caplog.at_level(logging.WARNING, logger="components.identity"):
            BuildUserContextQuery(port).execute(user_id="u1")

        assert any("active_workspace_not_member" in r.message for r in caplog.records)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
