"""Invited user registration port.

Extracted from ``components.team.ports.team_invited_user_registration_port``.
"""

from __future__ import annotations

import abc


class InvitedUserRegistrationPort(abc.ABC):
    """Register or retrieve a user who was invited via email."""

    @abc.abstractmethod
    def register_or_get_invited_user(
        self,
        *,
        email: str,
        name: str,
        workspace_id,
        team_name: str,
        request=None,
        site_domain: str | None = None,
    ) -> object:
        """Register a new user from an invitation or return the existing user."""
