"""Use case: pick up SCHEDULED newsletters whose time has arrived + send them.

Runs on a 5-minute Beat cadence. Per row:

1. Atomic CAS scheduled→sending via ``try_claim_scheduled_for_send`` so
   concurrent runners can't double-send.
2. Call ``SendNewsletterUseCase`` — same path the human-clicks-Send
   button uses, so behaviour stays consistent. The use case handles
   per-recipient dispatch, mark_sent, and the NewsletterSent event.
3. On exception: ``mark_send_failed`` with the truncated error message
   on metadata. The batch task does NOT auto-retry — re-sending a
   partially-delivered newsletter would double-message early
   recipients. The editor UI surfaces SEND_FAILED with a Retry button
   that re-enters the human flow.

Doesn't itself do the database work — delegates to the store + the
send use case. Returns a summary the Celery task uses for logging.
"""

from __future__ import annotations

import datetime
import logging
from dataclasses import dataclass

from components.content.application.ports.newsletter_reader_port import (
    NewsletterReaderPort,
)
from components.content.application.ports.newsletter_store_port import (
    NewsletterStorePort,
)
from components.content.application.use_cases.send_newsletter_use_case import (
    SendNewsletterUseCase,
)
from components.content.domain.enums import NewsletterStatus
from components.content.domain.errors import NewsletterUnverifiedFiguresError

logger = logging.getLogger(__name__)

# Per-tick batch cap so a backlog of scheduled rows doesn't tie up the
# worker. Whatever doesn't get processed this tick rolls over to the
# next 5-minute beat. 50/tick = up to 600 newsletters/hour per worker;
# bottleneck would be SES, not us.
_BATCH_LIMIT = 50


@dataclass
class DispatchDueScheduledNewslettersUseCase:
    newsletter_reader: NewsletterReaderPort
    newsletter_store: NewsletterStorePort
    send_newsletter: SendNewsletterUseCase

    def execute(self, *, now: datetime.datetime, system_user_id: int) -> dict[str, int]:
        """Return ``{"claimed", "sent", "failed", "skipped", "blocked"}``.

        ``blocked`` counts rows refused by the faithfulness gate (ungrounded
        figures) — marked SEND_FAILED for human review, never auto-sent.
        """

        from infrastructure.persistence.content.models import Newsletter

        due_ids = list(
            Newsletter.objects.filter(
                status=NewsletterStatus.SCHEDULED,
                scheduled_for__lte=now,
            )
            .order_by("scheduled_for")
            .values_list("id", flat=True)[:_BATCH_LIMIT]
        )

        claimed = 0
        sent = 0
        failed = 0
        skipped = 0
        blocked = 0

        for newsletter_id in due_ids:
            if not self.newsletter_store.try_claim_scheduled_for_send(
                newsletter_id=newsletter_id,
                now=now,
            ):
                skipped += 1
                continue
            claimed += 1
            try:
                # No override on the automated path — a scheduled newsletter
                # whose figures aren't grounded must NOT be silently emailed.
                self.send_newsletter.execute(
                    newsletter_id=newsletter_id,
                    triggered_by_user_id=system_user_id,
                    now=now,
                )
                sent += 1
            except NewsletterUnverifiedFiguresError as exc:
                # Skip + flag: surface SEND_FAILED with the unverified figures
                # so a human can review + send (or override) from the editor.
                logger.warning(
                    "scheduled_newsletter_blocked_unverified newsletter_id=%s "
                    "unsupported_count=%s",
                    newsletter_id,
                    len(exc.result.unsupported_numbers),
                )
                try:
                    self.newsletter_store.mark_send_failed(
                        newsletter_id=newsletter_id,
                        error_message=str(exc),
                    )
                except Exception:  # noqa: BLE001 — don't mask the block
                    logger.exception(
                        "scheduled_newsletter_mark_blocked_failed newsletter_id=%s",
                        newsletter_id,
                    )
                blocked += 1
            except Exception as exc:  # noqa: BLE001 — mark failed + continue batch
                logger.exception(
                    "scheduled_newsletter_send_failed newsletter_id=%s",
                    newsletter_id,
                )
                try:
                    self.newsletter_store.mark_send_failed(
                        newsletter_id=newsletter_id,
                        error_message=str(exc),
                    )
                except Exception:  # noqa: BLE001 — don't mask original failure
                    logger.exception(
                        "scheduled_newsletter_mark_failed_failed newsletter_id=%s",
                        newsletter_id,
                    )
                failed += 1

        return {
            "claimed": claimed,
            "sent": sent,
            "failed": failed,
            "skipped": skipped,
            "blocked": blocked,
        }
