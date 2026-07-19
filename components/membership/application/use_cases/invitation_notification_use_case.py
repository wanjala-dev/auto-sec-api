"""Use case: handle invitation notification lifecycle.

Extracted from ``components.team.application.use_cases.team_invitation_notification_use_case``.
"""

from __future__ import annotations

from components.membership.application.ports.invitation_notification_port import (
    InvitationNotificationPort,
)


class InvitationNotificationUseCase:
    def __init__(
        self,
        *,
        notification_port: InvitationNotificationPort,
    ) -> None:
        self.notification_port = notification_port

    def handle_invitation_issued(
        self,
        *,
        invitation,
        invited_user,
        actor_id,
        request=None,
        site_domain: str | None = None,
    ) -> None:
        self.notification_port.notify_invitation_issued(
            invitation=invitation,
            invited_user=invited_user,
            actor_id=actor_id,
            request=request,
            site_domain=site_domain,
        )

    def handle_invitation_accepted(
        self,
        *,
        invitation,
        actor,
    ) -> None:
        self.notification_port.notify_invitation_accepted(
            invitation=invitation,
            actor=actor,
        )
