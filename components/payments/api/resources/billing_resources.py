"""Output DTOs for billing endpoints."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BillingPlanResource:
    """Output DTO for billing plan data."""
    id: int | str | None = None
    title: str | None = None
    max_projects_per_team: int | None = None
    max_members_per_team: int | None = None
    max_tasks_per_project: int | None = None
    price: int | float | None = None
    currency: str | None = None
    billing_interval: str | None = None
    interval_count: int | None = None
    is_default: bool | None = None


@dataclass(frozen=True)
class BillingPlansCollectionResource:
    """Output DTO for billing plans list."""
    workspace_id: str | None = None
    plans: list[BillingPlanResource]
    count: int = 0


@dataclass(frozen=True)
class SubscriptionResource:
    """Output DTO for subscription data."""
    id: str | None = None
    status: str | None = None
    current_period_end: int | None = None
    current_period_start: int | None = None
    customer: str | None = None
    ended_at: int | None = None
    cancel_at: int | None = None
    cancel_at_period_end: bool | None = None
    canceled_at: int | None = None
    trial_start: int | None = None
    trial_end: int | None = None
    items: list[dict] | None = None


@dataclass(frozen=True)
class InvoiceResource:
    """Output DTO for invoice data."""
    id: str | None = None
    status: str | None = None
    amount_due: int | None = None
    amount_paid: int | None = None
    amount_remaining: int | None = None
    currency: str | None = None
    created: int | None = None
    due_date: int | None = None
    paid: bool | None = None
    payment_intent: str | None = None
    number: str | None = None
    pdf: str | None = None
    lines: list[dict] | None = None


@dataclass(frozen=True)
class BillingHistoryResource:
    """Output DTO for billing history."""
    workspace_id: str | None = None
    subscription_id: str | None = None
    invoices: list[InvoiceResource]
    has_more: bool | None = None
    next_cursor: str | None = None
    count: int = 0


@dataclass(frozen=True)
class BillingOverviewResource:
    """Output DTO for billing overview."""
    workspace_id: str | None = None
    plan: BillingPlanResource | None = None
    plan_status: str | None = None
    plan_end_date: str | None = None
    stripe_customer_id: str | None = None
    stripe_subscription_id: str | None = None
    subscription_status: str | None = None
    current_period_end: int | None = None
    default_payment_method_id: str | None = None
    payment_methods: list[dict] | None = None
    upcoming_invoice: dict | None = None


@dataclass(frozen=True)
class SetupIntentResource:
    """Output DTO for setup intent data."""
    id: str | None = None
    client_secret: str | None = None
    status: str | None = None
    usage: str | None = None
    flow_directions: list[str] | None = None


@dataclass(frozen=True)
class PlanPreviewResource:
    """Output DTO for plan change preview."""
    amount_due: int | None = None
    currency: str | None = None
    next_payment_attempt: int | None = None
    lines: list[dict] | None = None


@dataclass(frozen=True)
class PlanCancelResponseResource:
    """Output DTO for plan cancel response."""
    status: str | None = None
    plan: dict | None = None


@dataclass(frozen=True)
class PlanChangeResponseResource:
    """Output DTO for plan change response."""
    status: str | None = None
    subscription_id: str | None = None


@dataclass(frozen=True)
class CheckoutSessionResource:
    """Output DTO for checkout session."""
    id: str | None = None
    object: str | None = None
    client_secret: str | None = None
    url: str | None = None
    status: str | None = None
    success_url: str | None = None
    cancel_url: str | None = None
    payment_intent: str | None = None
    created: int | None = None
    expires_at: int | None = None
