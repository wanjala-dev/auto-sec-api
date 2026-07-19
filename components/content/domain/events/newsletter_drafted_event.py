"""Domain event: a newsletter draft was produced (by AI cadence or human)."""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from uuid import UUID

from components.shared_kernel.domain.events import DomainEvent


@dataclass(frozen=True, kw_only=True)
class NewsletterDrafted(DomainEvent):
    """Emitted when a Newsletter row is created.

    ``via_ai`` is True for cadence-driven generation (status=ai_drafted),
    False for human-authored drafts (status=draft). Downstream handlers
    (notification dispatch, RAG indexing) branch on this flag.
    """

    workspace_id: UUID
    newsletter_id: UUID
    title: str
    via_ai: bool
    author_id: int | None = None
    agent_type: str = ""
    period_start: datetime.date | None = None
    period_end: datetime.date | None = None
    metadata: dict = field(default_factory=dict)
