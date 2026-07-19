"""Port for querying user workspace/team membership context.

This abstracts away the ORM queries that the identity controller previously
ran inline against Workspace, WorkspaceMembership, and Team models.
"""
from __future__ import annotations

import abc
from typing import Any


class UserContextQueryPort(abc.ABC):
    """Read-only interface for user workspace/team context data."""

    @abc.abstractmethod
    def get_accessible_workspace_ids(self, *, user_id: Any) -> list[str]:
        """Return IDs of all workspaces the user can access (owner, member, team member)."""

    @abc.abstractmethod
    def get_org_membership_count(self, *, user_id: Any) -> int:
        """Return the count of workspaces the user belongs to."""

    @abc.abstractmethod
    def is_staff_or_superuser(self, *, user_id: Any) -> bool:
        """Check if user is staff or superuser (bypasses onboarding)."""

    @abc.abstractmethod
    def get_active_workspace_id(self, *, user_id: Any) -> str | None:
        """Return the user's active workspace ID from their profile, if set."""

    @abc.abstractmethod
    def infer_workspace_kind(self, *, workspace_id: Any) -> str | None:
        """Classify a workspace as 'personal' or 'organization' for UI routing."""

    @abc.abstractmethod
    def infer_workspace_role(self, *, user_id: Any, workspace_id: Any) -> str | None:
        """Return the user's effective role within a workspace."""

    @abc.abstractmethod
    def is_workspace_owner(self, *, user_id: Any, workspace_id: Any) -> bool:
        """Check if the user owns the given workspace."""

    @abc.abstractmethod
    def get_active_team_ids(self, *, user_id: Any) -> list[str]:
        """Return IDs of all active teams the user belongs to."""

    @abc.abstractmethod
    def get_workspace_default_currency(
        self, *, workspace_id: Any
    ) -> str | None:
        """Return the workspace's ISO 4217 ``default_currency`` or ``None``.

        Used by the user summary payload so the frontend can format
        amounts in the workspace's preferred currency before any
        payment method is connected. Returns ``None`` when the
        workspace doesn't exist or carries no currency yet — callers
        fall back to the platform default.
        """
