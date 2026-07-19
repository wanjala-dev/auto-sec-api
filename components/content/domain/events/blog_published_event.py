"""Domain event: a blog post (News) was published."""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from uuid import UUID

from components.shared_kernel.domain.events import DomainEvent


@dataclass(frozen=True, kw_only=True)
class BlogPublished(DomainEvent):
    """Emitted when a News row transitions to status=LIVE.

    Note: News.id is a UUIDField per ``infrastructure/persistence/workspaces/
    news/models.py``. The event captures the moment of publication so
    downstream handlers (search index, RAG ingestion, transparency feed
    update) can act independently.
    """

    workspace_id: UUID
    news_id: UUID
    title: str
    author_id: int
    category_id: int | None = None
    published_at: datetime.datetime
    metadata: dict = field(default_factory=dict)
