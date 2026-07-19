from __future__ import annotations

from typing import Any, Protocol


class TeamPlanBillingPort(Protocol):
    def checkout_team_plan(
        self,
        *,
        workspace: Any,
        plan: Any,
        customer_email: str | None,
        customer_name: str | None,
        user_id: str | None,
        team: Any | None = None,
        success_url: str,
        cancel_url: str,
        proration_behavior: str | None = None,
    ) -> tuple[dict[str, Any], int]: ...

    def preview_plan_change(
        self,
        *,
        workspace: Any,
        plan: Any,
    ) -> dict[str, Any] | None: ...

    def cancel_team_plan(
        self,
        *,
        workspace: Any,
        default_plan: Any | None = None,
    ) -> Any: ...

    def apply_plan_change(
        self,
        *,
        workspace: Any,
        plan: Any,
        proration_behavior: str = "create_prorations",
    ) -> dict[str, Any] | Any | None: ...

    def apply_team_plan_purchase(
        self,
        *,
        workspace: Any,
        metadata: dict[str, Any],
        subscription_id: str | None = None,
        customer_id: str | None = None,
        period_end: Any | None = None,
        method: Any | None = None,
    ) -> None: ...

    def sync_deleted_subscription(
        self,
        *,
        workspace: Any,
        default_plan: Any | None = None,
    ) -> Any | None: ...
