"""Use case: count how many of a set of emails are send-eligible subscribers.

The contacts segment-send preview calls this (through the WritingProvider) to
show "N of M contacts are subscribed and will receive this" before the admin
commits to a send. Content owns Subscriber + suppression, so the eligibility
question belongs here — contacts passes the segment's email addresses and gets
back the subscribed, non-suppressed count.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from components.content.application.ports.newsletter_reader_port import (
    NewsletterReaderPort,
)


@dataclass
class CountEligibleRecipientsUseCase:
    newsletter_reader: NewsletterReaderPort

    def execute(self, *, workspace_id: UUID, emails: Sequence[str]) -> int:
        return self.newsletter_reader.count_dispatch_targets_for_emails(
            workspace_id=workspace_id,
            emails=emails,
        )
