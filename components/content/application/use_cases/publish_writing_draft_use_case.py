"""Use case: flip a writing draft from DRAFT → PUBLISHED."""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from uuid import UUID

from components.content.application.ports.writing_draft_reader_port import (
    WritingDraftReaderPort,
)
from components.content.application.ports.writing_draft_store_port import (
    WritingDraftStorePort,
)
from components.content.domain.entities.writing_draft_entity import (
    WritingDraftEntity,
)
from components.content.domain.enums import WritingDraftStatus
from components.content.domain.errors import (
    WritingDraftInvalidTransitionError,
    WritingDraftNotFoundError,
)
from components.content.domain.events.writing_draft_published_event import (
    WritingDraftPublished,
)
from components.shared_kernel.infrastructure.adapters.celery_event_publisher import (
    CeleryEventPublisher,
)


@dataclass
class PublishWritingDraftUseCase:
    writing_draft_store: WritingDraftStorePort
    writing_draft_reader: WritingDraftReaderPort
    event_publisher: CeleryEventPublisher

    def execute(
        self,
        *,
        draft_id: UUID,
        actor_id: int,
        now: datetime.datetime,
    ) -> WritingDraftEntity:
        current = self.writing_draft_reader.get(draft_id=draft_id)
        if current is None:
            raise WritingDraftNotFoundError(str(draft_id))
        if current.status != WritingDraftStatus.DRAFT:
            raise WritingDraftInvalidTransitionError(
                f"Cannot publish draft {draft_id} from status {current.status}"
            )

        published = self.writing_draft_store.publish(draft_id=draft_id)

        self.event_publisher.publish(
            WritingDraftPublished(
                workspace_id=published.workspace_id,
                draft_id=published.id,
                title=published.title,
                kind=published.kind,
                author_id=published.author_id,
                published_at=now,
            )
        )
        return published
