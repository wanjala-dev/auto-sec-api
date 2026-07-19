"""Domain entity for a Newsletter."""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from uuid import UUID

from components.content.domain.enums import NewsletterStatus


@dataclass(frozen=True)
class NewsletterEntity:
    """
    Domain entity for a newsletter — a workspace-scoped, subscriber-targeted
    communication that is drafted (by AI cadence or a human) and explicitly
    sent by a human.

    Lifecycle:
        AI cadence: (new row, status=AI_DRAFTED) -> human edits -> status=DRAFT
                    -> human clicks Send -> status=SENT, sent_at=now
        Human compose: (new row, status=DRAFT) -> human clicks Send
                    -> status=SENT, sent_at=now
        Optional scheduling: status=DRAFT -> "Send at..." -> status=SCHEDULED,
                    scheduled_for=X -> dispatch task -> status=SENT

    Newsletter is NEVER auto-sent. The only code path that may set status=SENT
    is the human-triggered SendNewsletterUseCase. AI/Celery code paths may only
    create rows at AI_DRAFTED.
    """

    id: UUID
    workspace_id: UUID
    title: str
    content_html: str
    status: str
    created_at: datetime.datetime
    updated_at: datetime.datetime
    scheduled_for: datetime.datetime | None = None
    sent_at: datetime.datetime | None = None
    pdf_key: str = ""
    pdf_generated_at: datetime.datetime | None = None
    author_id: int | None = None
    ai_drafted_by_agent: str = ""
    period_start: datetime.date | None = None
    period_end: datetime.date | None = None
    content_payload: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)
    # Pre-send guardrail fields (added 2026-06-11). Editor exposes these
    # as separate inputs from ``title``; ``title`` stays the heading the
    # user sees in the editor + list, ``subject`` is what arrives in the
    # inbox. ``from_name`` overrides the workspace default display name
    # per send; ``reply_to`` overrides the workspace default reply
    # address.
    subject: str = ""
    preheader: str = ""
    from_name: str = ""
    reply_to: str = ""
    # Send metrics (task #25) — denormalized counters maintained by the
    # dispatch ledger + open-pixel endpoint. ``recipient_count`` is None
    # for sends that predate tracking (UI hides metrics rather than
    # showing a false zero).
    recipient_count: int | None = None
    failed_count: int | None = None
    unique_open_count: int = 0
    total_open_count: int = 0
    last_opened_at: datetime.datetime | None = None

    def __post_init__(self) -> None:
        if not self.workspace_id:
            raise ValueError("NewsletterEntity.workspace_id is required.")
        if not self.title:
            raise ValueError("NewsletterEntity.title is required.")
        NewsletterStatus.validate(self.status)
        if self.status == NewsletterStatus.SENT and self.sent_at is None:
            raise ValueError("NewsletterEntity in SENT status must have sent_at populated.")
        if self.status == NewsletterStatus.SCHEDULED and self.scheduled_for is None:
            raise ValueError("NewsletterEntity in SCHEDULED status must have scheduled_for populated.")

    @property
    def is_ai_drafted(self) -> bool:
        return self.status == NewsletterStatus.AI_DRAFTED

    @property
    def is_draft(self) -> bool:
        return self.status in {NewsletterStatus.DRAFT, NewsletterStatus.AI_DRAFTED}

    @property
    def is_sent(self) -> bool:
        return self.status == NewsletterStatus.SENT

    @property
    def is_scheduled(self) -> bool:
        return self.status == NewsletterStatus.SCHEDULED

    @property
    def has_pdf(self) -> bool:
        return bool(self.pdf_key)

    @property
    def covers_period(self) -> bool:
        return self.period_start is not None and self.period_end is not None
