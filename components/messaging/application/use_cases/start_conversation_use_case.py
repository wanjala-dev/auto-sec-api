"""Use case: start a new private conversation (find-or-create)."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from components.messaging.domain.entities.conversation_entity import Conversation, Participant
from components.messaging.domain.errors import (
    CannotMessageOutsideSharedWorkspaceError,
    CannotMessageSelfError,
)
from components.messaging.domain.value_objects import ConversationType, ParticipantRole


@dataclass
class StartConversationResult:
    conversation: Conversation
    created: bool


@dataclass
class StartConversationUseCase:
    conversation_repo: object  # ConversationRepositoryPort
    membership_check: object  # WorkspaceMembershipCheckPort

    def execute(
        self,
        *,
        initiator_id: UUID,
        recipient_id: UUID,
        workspace_id: UUID | None = None,
    ) -> StartConversationResult:
        if initiator_id == recipient_id:
            raise CannotMessageSelfError("Cannot start a conversation with yourself.")

        # Gate: you may only DM someone you share a workspace with.
        if not self.membership_check.shares_workspace(initiator_id, recipient_id):
            raise CannotMessageOutsideSharedWorkspaceError(
                "You can only message people you share a workspace with."
            )

        # Check for existing conversation.
        existing = self.conversation_repo.find_private_between(
            initiator_id, recipient_id, workspace_id,
        )
        if existing is not None:
            return StartConversationResult(conversation=existing, created=False)

        # Build the new conversation entity.
        conv_type = ConversationType.WORKSPACE if workspace_id else ConversationType.PRIVATE
        conversation = Conversation(
            conversation_type=conv_type,
            workspace_id=workspace_id,
            participants=[
                Participant(user_id=initiator_id, role=ParticipantRole.OWNER),
                Participant(user_id=recipient_id, role=ParticipantRole.MEMBER),
            ],
        )
        conversation.validate_new_private()

        created = self.conversation_repo.create(conversation)
        return StartConversationResult(conversation=created, created=True)
