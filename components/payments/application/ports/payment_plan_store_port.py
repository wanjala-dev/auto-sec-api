from __future__ import annotations

from typing import Any, Protocol


class PaymentPlanStorePort(Protocol):
    """Resolve the active plan for an already selected payment method."""

    def resolve_plan_for_method(
        self,
        *,
        method: Any,
        context: str,
        plan_slug: str | None = None,
        recipient: Any | None = None,
        prefer_recurring: bool | None = None,
    ) -> Any | None: ...
