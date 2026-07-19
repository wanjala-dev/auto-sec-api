from __future__ import annotations

from typing import Any

from components.payments.application.ports.payment_method_selection_port import (
    PaymentMethodSelectionPort,
)
from components.payments.application.ports.payment_plan_store_port import PaymentPlanStorePort


class ResolvePaymentMethodAndPlanUseCase:
    def __init__(
        self,
        payment_method_selection: PaymentMethodSelectionPort,
        payment_plans: PaymentPlanStorePort,
    ):
        self.payment_method_selection = payment_method_selection
        self.payment_plans = payment_plans

    def execute(
        self,
        *,
        workspace: Any,
        context: str,
        payment_method_id: str | None = None,
        plan_slug: str | None = None,
        recipient: Any | None = None,
        prefer_recurring: bool | None = None,
    ) -> tuple[Any | None, Any | None]:
        method = self.payment_method_selection.resolve_method(
            workspace=workspace,
            context=context,
            payment_method_id=payment_method_id,
        )
        if not method:
            return None, None

        plan = self.payment_plans.resolve_plan_for_method(
            method=method,
            context=context,
            plan_slug=plan_slug,
            recipient=recipient,
            prefer_recurring=prefer_recurring,
        )
        if plan or not payment_method_id:
            return method, plan

        fallback_method = self.payment_method_selection.resolve_method(
            workspace=workspace,
            context=context,
            payment_method_id=None,
        )
        if not fallback_method or getattr(fallback_method, "id", None) == getattr(method, "id", None):
            return method, plan

        fallback_plan = self.payment_plans.resolve_plan_for_method(
            method=fallback_method,
            context=context,
            plan_slug=plan_slug,
            recipient=recipient,
            prefer_recurring=prefer_recurring,
        )
        return fallback_method, fallback_plan
