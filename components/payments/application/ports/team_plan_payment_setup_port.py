from __future__ import annotations

from typing import Any, Protocol


class TeamPlanPaymentSetupPort(Protocol):
    def ensure_subscription_payment_method(self, *, workspace: Any) -> Any: ...

    def ensure_platform_customer(
        self,
        *,
        workspace: Any,
        method: Any,
        email: str | None = None,
        name: str | None = None,
    ) -> str: ...

    def ensure_team_plan_payment_plan(
        self,
        *,
        workspace: Any,
        plan: Any,
        method: Any,
        currency_override: str | None = None,
    ) -> Any | None: ...
