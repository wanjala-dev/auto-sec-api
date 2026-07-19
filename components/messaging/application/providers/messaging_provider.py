"""Composition root for the messaging bounded context.

Wires ports to concrete adapters and builds fully-constructed use cases.
Controllers and other primary adapters import from here.
"""

from __future__ import annotations

from components.messaging.application.use_cases.delete_message_use_case import (
    DeleteMessageUseCase,
)
from components.messaging.application.use_cases.get_conversation_messages_use_case import (
    GetConversationMessagesUseCase,
)
from components.messaging.application.use_cases.list_conversations_use_case import (
    ListConversationsUseCase,
)
from components.messaging.application.use_cases.manage_conversation_use_case import (
    ArchiveConversationUseCase,
    MuteConversationUseCase,
    StarConversationUseCase,
)
from components.messaging.application.use_cases.mark_read_use_case import (
    MarkReadUseCase,
)
from components.messaging.application.use_cases.send_message_use_case import (
    SendMessageUseCase,
)
from components.messaging.application.use_cases.start_conversation_use_case import (
    StartConversationUseCase,
)
from components.messaging.infrastructure.repositories.orm_conversation_repository import (
    OrmConversationRepository,
    OrmMessageRepository,
)


def _conversation_repo():
    return OrmConversationRepository()


def _message_repo():
    return OrmMessageRepository()


def _membership_check():
    from components.messaging.infrastructure.adapters.workspace_membership_check_adapter import (
        WorkspaceMembershipCheckAdapter,
    )

    return WorkspaceMembershipCheckAdapter()


def make_start_conversation() -> StartConversationUseCase:
    return StartConversationUseCase(
        conversation_repo=_conversation_repo(),
        membership_check=_membership_check(),
    )


def make_send_message() -> SendMessageUseCase:
    from components.messaging.infrastructure.adapters.message_notification_adapter import (
        MessageNotificationAdapter,
    )
    from components.messaging.infrastructure.adapters.share_notification_adapter import (
        ShareNotificationAdapter,
    )

    return SendMessageUseCase(
        conversation_repo=_conversation_repo(),
        message_repo=_message_repo(),
        share_notifier=ShareNotificationAdapter(),
        message_notifier=MessageNotificationAdapter(),
    )


def make_list_conversations() -> ListConversationsUseCase:
    return ListConversationsUseCase(
        conversation_repo=_conversation_repo(),
        message_repo=_message_repo(),
    )


def make_get_messages() -> GetConversationMessagesUseCase:
    return GetConversationMessagesUseCase(
        conversation_repo=_conversation_repo(),
        message_repo=_message_repo(),
    )


def make_mark_read() -> MarkReadUseCase:
    return MarkReadUseCase(
        conversation_repo=_conversation_repo(),
        message_repo=_message_repo(),
    )


def make_archive_conversation() -> ArchiveConversationUseCase:
    return ArchiveConversationUseCase(conversation_repo=_conversation_repo())


def make_star_conversation() -> StarConversationUseCase:
    return StarConversationUseCase(conversation_repo=_conversation_repo())


def make_mute_conversation() -> MuteConversationUseCase:
    return MuteConversationUseCase(conversation_repo=_conversation_repo())


def make_delete_message() -> DeleteMessageUseCase:
    return DeleteMessageUseCase(
        conversation_repo=_conversation_repo(),
        message_repo=_message_repo(),
    )
