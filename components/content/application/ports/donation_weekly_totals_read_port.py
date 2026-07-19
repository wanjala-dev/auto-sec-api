"""Port: read weekly donation totals for a workspace.

The newsletter chart resolver shapes the chart payload; the actual
ORM aggregation lives behind this port so the domain/application
layers stay framework-free.
"""

from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Protocol
from uuid import UUID


class DonationWeeklyTotalsReadPort(Protocol):
    def fetch_weekly_totals(
        self,
        *,
        workspace_id: UUID,
        window_start: datetime.date,
        window_end_exclusive: datetime.date,
    ) -> dict[datetime.date, Decimal]:
        """Return ``{week_start_date: total}`` for the window.

        Missing weeks should NOT appear in the dict — the caller fills
        zero-flow buckets so the chart series is dense.
        """
        ...
