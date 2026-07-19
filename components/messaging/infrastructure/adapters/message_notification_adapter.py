"""Notify participants of a new direct message (T1-S9 emitter #1).

Implements ``MessageNotificationPort`` over the canonical
``NotificationDispatcher`` funnel — the ONLY sanctioned way to create
notification rows from another context (preference filtering, dedup,
delivery fan-out all live there).

Dedup design: the verb is a STABLE string ("sent you a message") and the
target is the Conversation row, so a burst of messages in one
conversation collapses into a single row inside the dispatcher's
5-minute window, while messages in different conversations stay
distinct. The per-message ``preview`` rides in metadata, which is NOT
part of the dedup identity.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from uuid import UUID

from components.notifications.infrastructure.adapters.notification_service import (
    NotificationDispatcher,
)
from infrastructure.persistence.notifications.models import Notification

logger = logging.getLogger(__name__)

_PREVIEW_MAX_LENGTH = 120


class MessageNotificationAdapter:
    def notify_new_message(
        self,
        *,
        sender_id: UUID,
        recipient_user_ids: Sequence[UUID],
        conversation_id: UUID,
        workspace_id: UUID | None = None,
        preview: str = "",
    ) -> None:
        if not recipient_user_ids:
            return
        try:
            from django.contrib.auth import get_user_model

            from infrastructure.persistence.messaging.models import Conversation

            User = get_user_model()
            sender = User.objects.filter(pk=sender_id).first()
            if sender is None:
                return
            recipients = list(User.objects.filter(pk__in=list(recipient_user_ids)))
            if not recipients:
                return

            conversation = Conversation.objects.filter(pk=conversation_id).select_related("workspace").first()
            workspace = getattr(conversation, "workspace", None)

            trimmed_preview = (preview or "").strip()
            if len(trimmed_preview) > _PREVIEW_MAX_LENGTH:
                trimmed_preview = trimmed_preview[: _PREVIEW_MAX_LENGTH - 1] + "…"

            NotificationDispatcher().dispatch(
                actor=sender,
                workspace=workspace,
                verb="sent you a message",
                notification_type=Notification.NotificationType.MESSAGE,
                recipients=recipients,
                metadata={
                    "conversation_id": str(conversation_id),
                    "preview": trimmed_preview,
                },
                target=conversation,
            )
        except Exception:
            # Decoration on the send path — never fail the message itself.
            logger.exception(
                "message_notify.failed conversation_id=%s sender_id=%s",
                conversation_id,
                sender_id,
            )
