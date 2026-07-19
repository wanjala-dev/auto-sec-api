"""
ORM adapter implementing ConversationRepositoryPort and ConversationMessageRepositoryPort.
"""

from __future__ import annotations

from typing import Any

from components.agents.application.ports.conversation_port import (
    ConversationMessageRepositoryPort,
    ConversationRepositoryPort,
)


class OrmConversationRepository(ConversationRepositoryPort):
    def get_by_id(self, conversation_id: str, *, user: Any) -> Any | None:
        from infrastructure.persistence.ai.conversations.models import Conversation

        return Conversation.objects.filter(id=conversation_id, user=user).first()

    def list_for_user(self, user: Any) -> Any:
        from django.db.models import Count, Q

        from infrastructure.persistence.ai.conversations.models import Conversation

        # ``ConversationListSerializer`` renders ``message_count`` per row; the
        # single-query annotation replaces the per-conversation
        # ``obj.messages.count()`` N+1 (the list endpoint is unpaginated, so
        # the per-row count scaled with the user's whole conversation history).
        # Document-assist threads live in-editor (their own launcher), so they
        # are excluded from the human-facing Messages conversation list.
        #
        # NULL-safe exclude: a bare ``.exclude(metadata__surface=...)`` also
        # drops rows whose ``surface`` key is absent/NULL — SQL three-valued
        # logic makes ``NOT (NULL = 'document_assist')`` evaluate to NULL
        # (falsy), which silently hid every conversation created without a
        # ``surface`` in its metadata. Match the key explicitly instead
        # (``isnull`` OR ``!=`` the sentinel) so only real document-assist
        # threads are excluded.
        return (
            Conversation.objects.filter(user=user)
            .filter(
                Q(metadata__surface__isnull=True)
                | ~Q(metadata__surface="document_assist")
            )
            .annotate(message_count=Count("messages"))
        )

    def create(self, **kwargs: Any) -> Any:
        from infrastructure.persistence.ai.conversations.models import Conversation

        return Conversation.objects.create(**kwargs)

    def delete(self, conversation_id: str, *, user: Any) -> bool:
        from infrastructure.persistence.ai.conversations.models import Conversation

        conversation = Conversation.objects.filter(id=conversation_id, user=user).first()
        if conversation is None:
            return False
        conversation.delete()
        return True

    def clear_messages(self, conversation_id: str, *, user: Any) -> bool:
        from infrastructure.persistence.ai.conversations.models import Conversation

        conversation = Conversation.objects.filter(id=conversation_id, user=user).first()
        if conversation is None:
            return False
        conversation.messages.all().delete()
        return True

    def find_document_assist(self, *, user: Any, artifact_type: str, artifact_id: str) -> Any | None:
        from infrastructure.persistence.ai.conversations.models import Conversation

        return (
            Conversation.objects.filter(
                user=user,
                metadata__surface="document_assist",
                metadata__artifact_type=artifact_type,
                metadata__artifact_id=str(artifact_id),
            )
            .order_by("-updated_at")
            .first()
        )

    def list_messages(self, conversation: Any) -> Any:
        return conversation.messages.all().order_by("created_at").prefetch_related("feedback")


class OrmConversationMessageRepository(ConversationMessageRepositoryPort):
    def create_message(self, *, conversation: Any, role: str, content: str, **kwargs: Any) -> Any:
        from infrastructure.persistence.ai.conversations.models import ConversationMessage

        return ConversationMessage.objects.create(
            conversation=conversation,
            role=role,
            content=content,
            **kwargs,
        )

    def update_streaming_status(self, message: Any, *, content: str, is_streaming: bool) -> None:
        message.content = content
        message.is_streaming = is_streaming
        message.save()
