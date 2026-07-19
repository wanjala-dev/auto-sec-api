"""Port: aggregate DeepRunLog rows for a plan.

The agent chat use case needs total tokens-used / total-cost for a
plan id. The actual ORM aggregation lives behind this port so the
application layer stays framework-free.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Protocol


class DeepRunAggregatorPort(Protocol):
    def aggregate_plan_totals(self, *, plan_id: str) -> dict[str, Decimal]:
        """Return ``{'tokens_total': ..., 'cost_total': ...}`` for the plan."""
        ...
