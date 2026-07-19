"""Weekly donation totals — stubbed in the auto-sec fork.

Donations/sponsorship are not part of the security product, so the newsletter
chart data resolver has nothing to aggregate. Returns an empty mapping (the
caller fills zero buckets). Kept as a stub so the content context's provider
wiring resolves without the sponsorship context.
"""

from __future__ import annotations

import datetime
from decimal import Decimal
from uuid import UUID


class OrmDonationWeeklyTotalsAdapter:
    """No-op implementation of DonationWeeklyTotalsReadPort."""

    def fetch_weekly_totals(
        self,
        *,
        workspace_id: UUID,
        window_start: datetime.date,
        window_end_exclusive: datetime.date,
    ) -> dict[datetime.date, Decimal]:
        return {}
