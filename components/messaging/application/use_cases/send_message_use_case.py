"""Use case: send a message in an existing conversation."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from uuid import UUID

from components.messaging.domain.entities.message_entity import Message
from components.messaging.domain.errors import ConversationNotFoundError
from components.messaging.domain.value_objects import MessageType

logger = logging.getLogger(__name__)


@dataclass
class SendMessageUseCase:
    conversation_repo: object  # ConversationRepositoryPort
    message_repo: object  # MessageRepositoryPort
    # Optional side effect (task #21): when the message carries a
    # metadata.share card, tell the other participants (in-app + email).
    # Decoration — a notifier failure never fails the send.
    share_notifier: object | None = None  # ShareNotificationPort
    # Optional side effect (T1-S9): plain messages raise an in-app MESSAGE
    # notification for the other, non-muted participants. Same decoration
    # contract — a notifier failure never fails the send.
    message_notifier: object | None = None  # MessageNotificationPort

    def execute(
        self,
        *,
        conversation_id: UUID,
        sender_id: UUID,
        body: str = "",
        message_type: str = MessageType.TEXT,
        image=None,
        metadata: dict | None = None,
    ) -> Message:
        conversation = self.conversation_repo.find_by_id(conversation_id)
        if conversation is None:
            raise ConversationNotFoundError(f"Conversation {conversation_id} not found.")

        # Verify the sender is a participant.
        conversation.ensure_participant(sender_id)

        # An uploaded image implies an image message.
        if image is not None:
            message_type = MessageType.IMAGE.value

        # Build and validate the message entity.
        message = Message(
            conversation_id=conversation_id,
            sender_id=sender_id,
            body=body,
            message_type=message_type,
            image=image,
            metadata=metadata or {},
        )
        message.validate()

        created = self.message_repo.create(message)

        share = (metadata or {}).get("share")
        if share and self.share_notifier is not None:
            recipient_ids = [p.user_id for p in conversation.participants if p.user_id != sender_id]
            try:
                self.share_notifier.notify_share(
                    sender_id=sender_id,
                    recipient_user_ids=recipient_ids,
                    share=share,
                    workspace_id=getattr(conversation, "workspace_id", None),
                )
            except Exception:
                logger.exception(
                    "send_message.share_notify_failed conversation_id=%s sender_id=%s",
                    conversation_id,
                    sender_id,
                )
        elif self.message_notifier is not None:
            # Plain message → MESSAGE notification for every other,
            # non-muted participant. Mute is per-participant domain state,
            # so the exclusion happens here, not in the adapter. Share-card
            # messages are excluded — the share leg above already notified.
            recipient_ids = [p.user_id for p in conversation.participants if p.user_id != sender_id and not p.is_muted]
            if recipient_ids:
                try:
                    self.message_notifier.notify_new_message(
                        sender_id=sender_id,
                        recipient_user_ids=recipient_ids,
                        conversation_id=conversation_id,
                        workspace_id=getattr(conversation, "workspace_id", None),
                        preview=created.body or "",
                    )
                except Exception:
                    logger.exception(
                        "send_message.message_notify_failed conversation_id=%s sender_id=%s",
                        conversation_id,
                        sender_id,
                    )

        return created
