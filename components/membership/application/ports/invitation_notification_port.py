"""Invitation notification port — outbound notifications for invitations.

Extracted from ``components.team.ports.team_invitation_notification_port``.
"""

from __future__ import annotations

import abc


class InvitationNotificationPort(abc.ABC):
    """Outbound notifications for invitation lifecycle events."""

    @abc.abstractmethod
    def notify_invitation_issued(
        self,
        *,
        invitation,
        invited_user,
        actor_id,
        request=None,
        site_domain: str | None = None,
    ) -> None:
        """Notify when an invitation has been issued."""

    @abc.abstractmethod
    def notify_invitation_accepted(
        self,
        *,
        invitation,
        actor,
    ) -> None:
        """Notify when an invitation has been accepted."""
