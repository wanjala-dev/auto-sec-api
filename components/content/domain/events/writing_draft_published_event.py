"""Domain event: a writing draft (letter / update / summary / memo) was published."""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from uuid import UUID

from components.shared_kernel.domain.events import DomainEvent


@dataclass(frozen=True, kw_only=True)
class WritingDraftPublished(DomainEvent):
    """Emitted when a WritingDraft transitions to status=published.

    Downstream handlers may surface the draft in a workspace activity feed,
    index it for search, or attach it to a related entity (e.g., funder
    record for a thank-you letter).
    """

    workspace_id: UUID
    draft_id: UUID
    title: str
    kind: str
    author_id: int
    published_at: datetime.datetime
    metadata: dict = field(default_factory=dict)
