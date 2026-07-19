"""Provider/composition root for messaging repository access.

Controllers that need direct repository operations (e.g. computing the
unread-message counts projection) go through this provider instead of
importing ``OrmConversationRepository`` / ``OrmMessageRepository``
directly from the infrastructure layer.

The ``messaging_provider`` module already wires repositories into use
cases for the standard CQRS flows; this provider exists for the narrow
cases where a controller needs a simple read projection without a full
use case wrapper.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID


class ConversationRepositoryProvider:
    """Lazy facade over the messaging ORM repositories.

    All methods lazy-import the concrete adapters so this module has
    no top-level dependency on Django or the infrastructure layer.
    """

    def conversation_repository(self) -> Any:
        from components.messaging.infrastructure.repositories.orm_conversation_repository import (
            OrmConversationRepository,
        )

        return OrmConversationRepository()

    def message_repository(self) -> Any:
        from components.messaging.infrastructure.repositories.orm_conversation_repository import (
            OrmMessageRepository,
        )

        return OrmMessageRepository()

    def unread_count(self, user_id: UUID) -> dict[UUID, int]:
        """Return ``{conversation_id: unread_count}`` for the given user.

        Thin pass-through to ``OrmMessageRepository.unread_count`` so
        controllers never need to touch the infrastructure layer.
        """
        from components.messaging.infrastructure.repositories.orm_conversation_repository import (
            OrmMessageRepository,
        )

        return OrmMessageRepository().unread_count(user_id)


_default = ConversationRepositoryProvider()


def get_conversation_repository_provider() -> ConversationRepositoryProvider:
    return _default
