from __future__ import annotations

from typing import Any

from django.utils.text import slugify

from components.payments.application.ports.payment_plan_store_port import (
    PaymentPlanStorePort,
)
from infrastructure.persistence.workspaces.payments.models import PaymentPlan, WorkspacePaymentMethod


class OrmPaymentPlanRepository(PaymentPlanStorePort):
    """Resolve checkout plans from the legacy ORM models."""

    def resolve_plan_for_method(
        self,
        *,
        method: WorkspacePaymentMethod,
        context: str,
        plan_slug: str | None = None,
        recipient: Any | None = None,
        prefer_recurring: bool | None = None,
    ) -> PaymentPlan | None:
        plan = None
        plan_qs = method.plans.filter(context=context, is_active=True)
        if prefer_recurring is not None:
            plan_qs = plan_qs.filter(is_recurring=prefer_recurring)
        if plan_slug:
            normalized_slug = slugify(plan_slug)
            slug_filters = [plan_slug]
            if normalized_slug and normalized_slug not in slug_filters:
                slug_filters.append(normalized_slug)

            if recipient:
                plan = plan_qs.filter(slug__in=slug_filters, recipient=recipient).first()
            if not plan:
                plan = plan_qs.filter(slug__in=slug_filters, recipient__isnull=True).first()
            if not plan:
                plan = plan_qs.filter(label__iexact=plan_slug).first()

        if not plan and recipient:
            plan = plan_qs.filter(recipient=recipient).order_by("sort_order", "created_at").first()
        if not plan:
            plan = plan_qs.filter(recipient__isnull=True).order_by("sort_order", "created_at").first()

        return plan
