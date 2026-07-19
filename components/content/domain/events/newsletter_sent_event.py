"""Domain event: a newsletter was sent to subscribers."""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from uuid import UUID

from components.shared_kernel.domain.events import DomainEvent


@dataclass(frozen=True, kw_only=True)
class NewsletterSent(DomainEvent):
    """Emitted when SendNewsletterUseCase successfully dispatches a newsletter.

    Newsletters can ONLY be sent by an explicit human action (no cadence-driven
    auto-send). ``triggered_by_user_id`` is therefore always populated.
    """

    workspace_id: UUID
    newsletter_id: UUID
    title: str
    triggered_by_user_id: int
    sent_at: datetime.datetime
    subscriber_count: int
    metadata: dict = field(default_factory=dict)
