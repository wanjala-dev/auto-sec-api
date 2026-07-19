"""Invitation notification adapter.

Extracted from ``components.team.infrastructure.adapters.team_invitation_notification_adapter``.
Implements InvitationNotificationPort.
"""

from __future__ import annotations

import logging

from infrastructure.persistence.notifications.models import Notification
from components.notifications.infrastructure.adapters.notification_service import NotificationDispatcher
from components.team.infrastructure.adapters.utilities import send_invitation, send_invitation_accepted
from components.workspace.infrastructure.adapters.password_setup_url_builder import (
    build_password_setup_url,
)

logger = logging.getLogger(__name__)
notification_dispatcher = NotificationDispatcher()


class InvitationNotificationAdapter:
    def notify_invitation_issued(
        self,
        *,
        invitation,
        invited_user,
        actor_id,
        request=None,
        site_domain: str | None = None,
    ) -> None:
        self._emit_directory_contact_added_event(
            workspace_id=invitation.workspace_id,
            team_id=invitation.team_id,
            user_id=invited_user.id,
            actor_id=actor_id,
            email=getattr(invited_user, "email", "") or invitation.email,
        )

        email = (getattr(invited_user, "email", "") or invitation.email or "").strip().lower()
        password_setup_url = None
        if invited_user and not invited_user.has_usable_password():
            password_setup_url = build_password_setup_url(
                user=invited_user,
                request=request,
                site_domain=site_domain,
            )
        if email:
            send_invitation(
                email,
                invitation.code,
                invitation.team,
                password_setup_url=password_setup_url,
            )

        actor = getattr(invitation.team, "created_by", None)
        if not actor or not invited_user or invited_user == actor:
            return

        notification_dispatcher.dispatch(
            actor=actor,
            workspace=invitation.workspace,
            verb=f'invited you to join team "{invitation.team.title}"',
            notification_type=Notification.NotificationType.SYSTEM,
            recipients=[invited_user],
            metadata={
                "event": "team.invited",
                "team_id": str(invitation.team.id),
                "invitation_id": invitation.id,
            },
            target=invitation.team,
        )

    def notify_invitation_accepted(
        self,
        *,
        invitation,
        actor,
    ) -> None:
        team = invitation.team
        self._emit_directory_contact_added_event(
            workspace_id=invitation.workspace_id,
            team_id=team.id,
            user_id=actor.id,
            actor_id=actor.id,
            email=actor.email,
        )

        send_invitation_accepted(team, invitation)

        recipients = list(team.members.exclude(id=actor.id))
        if not recipients:
            return

        accepted_at = invitation.accepted_at.isoformat() if invitation.accepted_at else None
        notification_dispatcher.dispatch(
            actor=actor,
            workspace=invitation.workspace,
            verb=f'joined team "{team.title}"',
            notification_type=Notification.NotificationType.SYSTEM,
            recipients=recipients,
            metadata={
                "event": "team.invitation_accepted",
                "team_id": str(team.id),
                "invitation_id": invitation.id,
                "accepted_at": accepted_at,
            },
            target=team,
        )

    @staticmethod
    def _emit_directory_contact_added_event(*, workspace_id, team_id, user_id, actor_id=None, email=None):
        try:
            from components.workflow.infrastructure.adapters.dispatcher import emit_workflow_event

            emit_workflow_event(
                workspace_id=str(workspace_id),
                source_type="directory",
                trigger_type="contact_added",
                payload={
                    "workspace_id": str(workspace_id),
                    "team_id": str(team_id),
                    "target_type": "contact",
                    "target_id": str(user_id),
                    "contact_id": str(user_id),
                    "user_id": str(actor_id or user_id),
                    "contact_email": email or "",
                },
                source_id=str(team_id),
                idempotency_key=f"directory_contact_added:{workspace_id}:{team_id}:{user_id}",
            )
        except Exception:
            logger.exception("Failed to emit directory contact_added workflow event")
