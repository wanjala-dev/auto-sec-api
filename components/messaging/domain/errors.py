"""Domain errors for the messaging bounded context."""

from __future__ import annotations

from components.shared_kernel.domain.errors import (
    DomainError,
    NotFoundError,
    ValidationError,
)


class MessagingDomainError(DomainError):
    """Base error for all messaging-domain workflows."""


class ConversationNotFoundError(MessagingDomainError, NotFoundError):
    """Raised when a conversation cannot be located."""


class MessageNotFoundError(MessagingDomainError, NotFoundError):
    """Raised when a message cannot be located."""


class NotAParticipantError(MessagingDomainError, ValidationError):
    """Raised when a user attempts an action on a conversation they are not part of."""


class DuplicateConversationError(MessagingDomainError, ValidationError):
    """Raised when trying to create a conversation that already exists between the same participants."""


class CannotMessageSelfError(MessagingDomainError, ValidationError):
    """Raised when a user attempts to start a conversation with themselves."""


class CannotMessageOutsideSharedWorkspaceError(MessagingDomainError, ValidationError):
    """Raised when two users share no workspace and therefore may not DM.

    Direct messaging is gated on workspace-membership overlap: a user may
    only start a conversation with someone they share at least one
    workspace with. Mapped to HTTP 403 by the controller.
    """


class MessageBodyEmptyError(MessagingDomainError, ValidationError):
    """Raised when a message body is blank or whitespace-only."""
