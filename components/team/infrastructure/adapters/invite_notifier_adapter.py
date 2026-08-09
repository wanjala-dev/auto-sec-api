"""Adapter: send the persona-invite email + in-app notification.

Implements :class:`InviteNotifierPort`. Re-fetches the ORM ``Invitation`` (and
inviter/recipient) by id and performs the magic-link email + in-app notification,
swallowing failures exactly as the create-invite use case did inline — email is
the primary channel; the bell-icon ping is a nicety. Keeping this here confines
the ORM + email/notification infrastructure to the adapter.
"""

from __future__ import annotations

import logging

from components.team.application.ports.invite_notifier_port import InviteNotifierPort

logger = logging.getLogger("invitations")


class InviteNotifierAdapter(InviteNotifierPort):
    def send_invitation_email(
        self,
        *,
        invitation_id: str,
        inviter_user_id: str | None,
        is_existing_user: bool,
    ) -> None:
        # Queue the SMTP send to Celery, post-commit (>100ms rule): the task
        # re-reads the invitation row, so it must see the committed token. A
        # send failure retries + logs loudly in the worker instead of being
        # swallowed here while the API claims "Invite sent". The enqueue
        # choreography lives ONCE in the shared dispatch helper.
        from components.team.infrastructure.adapters.persona_invitation_email_dispatch import (
            queue_persona_invitation_email,
        )

        queue_persona_invitation_email(
            invitation_id,
            inviter_user_id=inviter_user_id,
            is_existing_user=is_existing_user,
        )

    def notify_existing_user(
        self,
        *,
        invitation_id: str,
        inviter_user_id: str | None,
        recipient_user_id: str,
        token: str,
    ) -> None:
        from infrastructure.persistence.team.models import Invitation
        from infrastructure.persistence.users.models import CustomUser

        if not inviter_user_id:
            return

        invitation = Invitation.objects.select_related("workspace").filter(id=invitation_id).first()
        if invitation is None:
            return
        inviter_user = CustomUser.objects.filter(id=inviter_user_id).first()
        recipient = CustomUser.objects.filter(id=recipient_user_id).first()
        if inviter_user is None or recipient is None:
            return

        workspace = invitation.workspace
        try:
            from components.notifications.application.providers.notification_factory_provider import (
                get_notification_factory_provider,
            )

            get_notification_factory_provider().dispatch(
                actor=inviter_user,
                workspace=workspace,
                verb=f"invited you to join {workspace.workspace_name or 'a workspace'}",
                notification_type="workspace_invitation",
                recipients=[recipient],
                target=invitation,
                metadata={
                    "invitation_id": str(invitation.id),
                    "persona": invitation.persona,
                    "role": invitation.role,
                    "token": token,
                },
            )
        except Exception:
            logger.exception("persona invite in-app notification failed for %s", invitation.email)
