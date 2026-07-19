"""Unified membership port — single interface for access control queries.

Other contexts call this port to answer "can this user do X in this scope?"
without depending on the underlying membership models.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class AccessCheckResult:
    """Result of an access check."""

    allowed: bool
    role: str | None = None
    reason: str = ""


@dataclass(frozen=True)
class ActiveContext:
    """The user's currently active workspace and team."""

    user_id: int
    active_workspace_id: str | None = None
    active_team_id: int | None = None


class MembershipPort(abc.ABC):
    """Unified membership query interface.

    Replaces scattered ``user_is_workspace_member()`` /
    ``_require_team_member()`` calls with a single port.
    """

    @abc.abstractmethod
    def check_workspace_access(
        self,
        *,
        user_id: int,
        workspace_id: str,
        required_role: str | None = None,
    ) -> AccessCheckResult:
        """Check if a user has the required role in a workspace."""

    @abc.abstractmethod
    def check_team_access(
        self,
        *,
        user_id: int,
        team_id: int,
        required_role: str | None = None,
    ) -> AccessCheckResult:
        """Check if a user has the required role in a team."""

    @abc.abstractmethod
    def resolve_active_context(
        self,
        *,
        user_id: int,
    ) -> ActiveContext:
        """Resolve the user's currently active workspace and team."""

    @abc.abstractmethod
    def list_workspace_roles(
        self,
        *,
        user_id: int,
        workspace_id: str,
    ) -> list[str]:
        """List all roles a user holds in a workspace."""

    @abc.abstractmethod
    def list_team_roles(
        self,
        *,
        user_id: int,
        team_id: int,
    ) -> list[str]:
        """List all roles a user holds in a team."""
