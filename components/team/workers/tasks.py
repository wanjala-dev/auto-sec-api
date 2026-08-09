"""Celery entry points for the team bounded context.

Tasks are PRIMARY ADAPTERS — an external trigger (broker delivery or the
Beat scheduler) driving the application, just like an HTTP request. Each
task is a thin wrapper; ORM imports stay lazy (inside functions) so this
module is safe to import from ``api/celery.py`` before the app registry
is ready.

Tasks here:

* ``team.send_persona_invitation_email`` — deliver the persona-invite
  magic-link email for one invitation. Queued (post-commit) by the
  invite-create and invite-resend flows so SMTP never blocks the request
  path (>100ms rule). FAIL-LOUD: a backend send failure raises so Celery's
  retry/backoff owns transient SMTP trouble — no silent "Invite sent"
  while nothing was delivered.
"""

from __future__ import annotations

import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(
    name="team.send_persona_invitation_email",
    bind=True,
    max_retries=3,
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
    soft_time_limit=60,
    time_limit=90,
)
def send_persona_invitation_email(
    self,
    invitation_id: str,
    inviter_user_id: str | None = None,
    is_existing_user: bool = False,
) -> str:
    """Send the magic-link email for one persona invitation.

    Idempotent: re-running re-sends the CURRENT token for a still-pending
    invitation; revoked/accepted/expired invitations are skipped (the token
    in a stale email would be refused by the accept endpoint anyway).
    """
    from components.team.infrastructure.adapters.utilities import send_persona_invitation
    from infrastructure.persistence.team.models import Invitation
    from infrastructure.persistence.users.models import CustomUser

    logger.info(
        "team.send_persona_invitation_email started invitation_id=%s task_id=%s",
        invitation_id,
        self.request.id,
    )

    invitation = Invitation.objects.select_related("workspace", "team").filter(id=invitation_id).first()
    if invitation is None:
        logger.info(
            "team.send_persona_invitation_email skipped (invitation gone) invitation_id=%s task_id=%s",
            invitation_id,
            self.request.id,
        )
        return "skipped_missing"
    if invitation.status != Invitation.INVITED:
        logger.info(
            "team.send_persona_invitation_email skipped (status=%s) invitation_id=%s task_id=%s",
            invitation.status,
            invitation_id,
            self.request.id,
        )
        return "skipped_status"

    inviter_user = None
    if inviter_user_id:
        inviter_user = CustomUser.objects.filter(id=inviter_user_id).first()

    send_persona_invitation(
        invitation,
        inviter_user=inviter_user,
        is_existing_user=is_existing_user,
    )
    logger.info(
        "team.send_persona_invitation_email completed invitation_id=%s task_id=%s",
        invitation_id,
        self.request.id,
    )
    return "sent"
