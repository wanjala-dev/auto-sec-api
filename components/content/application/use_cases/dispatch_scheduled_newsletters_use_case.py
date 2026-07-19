"""Use case: fan out scheduled newsletter generation across every workspace.

Invoked by the Celery Beat task ``content.dispatch_scheduled_newsletters``
at 07:00 UTC daily. For each workspace whose ``WorkspacePreference.settings
['newsletter_frequency']`` is not NONE and is due, call
``GenerateNewsletterUseCase`` to produce an ``AI_DRAFTED`` row.

This task NEVER sends newsletters. It only produces drafts for human
review (per the no-auto-send HARD RULE).
"""

from __future__ import annotations

import datetime
import logging
from dataclasses import dataclass, field
from typing import Callable, Protocol, Sequence
from uuid import UUID

from components.content.application.use_cases.generate_newsletter_use_case import (
    GenerateNewsletterUseCase,
)
from components.content.domain.enums import NewsletterCadence
from components.shared_kernel.domain.errors import ValidationError

logger = logging.getLogger(__name__)


class WorkspaceCadenceQueryPort(Protocol):
    """Reads ``WorkspacePreference.settings['newsletter_frequency']`` for
    every workspace with an active newsletter cadence."""

    def list_workspaces_due(
        self, *, now: datetime.datetime
    ) -> Sequence[tuple[UUID, str]]:
        """Return (workspace_id, cadence) pairs for workspaces whose
        newsletter cadence is set and whose next scheduled drop falls on
        or before ``now``. Implementations apply the idempotency window
        check (week-aligned for weekly, etc.) so this use case stays simple.
        """
        ...


class NewsletterMetricsCollectorPort(Protocol):
    """Pulls per-workspace metrics for the period being newslettered.

    Implementations run inline within the Celery task (per the
    Heavy-Aggregations HARD RULE, this is exactly where aggregations
    belong — NOT in a request-thread view).
    """

    def collect(
        self,
        *,
        workspace_id: UUID,
        period_start: datetime.date,
        period_end: datetime.date,
    ) -> dict: ...


def _compute_period(
    *, cadence: str, now: datetime.datetime
) -> tuple[datetime.date, datetime.date]:
    """Return (start, end) inclusive period for the given cadence ending
    at the day BEFORE ``now``.

    Weekly: previous 7 calendar days. Biweekly: previous 14. Monthly: the
    calendar month preceding the current one.
    """

    today = now.date()
    if cadence == NewsletterCadence.WEEKLY:
        end = today - datetime.timedelta(days=1)
        start = end - datetime.timedelta(days=6)
    elif cadence == NewsletterCadence.BIWEEKLY:
        end = today - datetime.timedelta(days=1)
        start = end - datetime.timedelta(days=13)
    elif cadence == NewsletterCadence.MONTHLY:
        first_of_this_month = today.replace(day=1)
        end = first_of_this_month - datetime.timedelta(days=1)
        start = end.replace(day=1)
    else:
        raise ValidationError(f"Unsupported newsletter cadence: {cadence!r}")
    return start, end


@dataclass
class DispatchScheduledNewslettersUseCase:
    cadence_queries: WorkspaceCadenceQueryPort
    metrics_collector: NewsletterMetricsCollectorPort
    generate_newsletter: GenerateNewsletterUseCase
    now_provider: Callable[[], datetime.datetime] = field(
        default=lambda: datetime.datetime.now(datetime.timezone.utc)
    )

    def execute(self) -> dict[str, int]:
        now = self.now_provider()
        due = self.cadence_queries.list_workspaces_due(now=now)
        produced = 0
        skipped = 0
        errors = 0

        for workspace_id, cadence in due:
            try:
                period_start, period_end = _compute_period(
                    cadence=cadence, now=now
                )
                metrics = self.metrics_collector.collect(
                    workspace_id=workspace_id,
                    period_start=period_start,
                    period_end=period_end,
                )
                # GenerateNewsletterUseCase is idempotent on (workspace,
                # period) — re-runs return the existing row.
                self.generate_newsletter.execute(
                    workspace_id=workspace_id,
                    period_start=period_start,
                    period_end=period_end,
                    metrics=metrics,
                )
                produced += 1
            except Exception:  # noqa: BLE001
                logger.exception(
                    "newsletter dispatch failed for workspace %s",
                    workspace_id,
                )
                errors += 1

        return {
            "due": len(due),
            "produced": produced,
            "skipped": skipped,
            "errors": errors,
        }
