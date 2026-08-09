"""Post-commit Celery enqueue for the persona-invite email.

The ONE canonical place that queues ``team.send_persona_invitation_email``
(dispatch-after-commit: the worker re-reads the invitation row, so it must
see the committed token; a send failure retries + logs loudly in the worker
instead of blocking or silently failing the request path). Consumed by the
invite-create flow (``InviteNotifierAdapter``) and — via
``InvitationEmailProvider`` — by the membership invite-resend endpoint, so
controllers never touch ``django.db`` transaction management themselves
(primary adapters are thin; the architecture suite enforces it).
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def queue_persona_invitation_email(
    invitation_id,
    *,
    inviter_user_id=None,
    is_existing_user: bool = False,
) -> None:
    """Queue the persona-invite email for ``invitation_id``, post-commit."""
    from django.db import transaction

    from components.team.workers.tasks import send_persona_invitation_email

    def _enqueue() -> None:
        send_persona_invitation_email.delay(
            str(invitation_id),
            str(inviter_user_id) if inviter_user_id else None,
            bool(is_existing_user),
        )
        logger.info("persona_invite_email_queued invitation_id=%s", invitation_id)

    transaction.on_commit(_enqueue)
