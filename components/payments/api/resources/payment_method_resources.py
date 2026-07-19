"""Output DTOs for payment method endpoints."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PaymentWebhookResource:
    """Output DTO for payment webhook endpoint data."""
    id: str | None = None
    name: str | None = None
    url: str | None = None
    signing_secret: str | None = None
    status: str | None = None
    last_error: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


@dataclass(frozen=True)
class PaymentPlanResource:
    """Output DTO for payment plan data."""
    id: str | None = None
    context: str | None = None
    slug: str | None = None
    label: str | None = None
    amount: int | float | None = None
    currency: str | None = None
    interval: str | None = None
    recipient_id: str | None = None
    recipient_name: str | None = None
    sort_order: int | None = None
    is_active: bool | None = None
    metadata: dict | None = None
    created_at: str | None = None
    updated_at: str | None = None


@dataclass(frozen=True)
class PaymentMethodResource:
    """Output DTO for payment method detail."""
    id: str | None = None
    workspace: str | None = None
    tenant: str | None = None
    provider: str | None = None
    display_name: str | None = None
    status: str | None = None
    is_primary: bool | None = None
    sort_order: int | None = None
    enabled_contexts: list[str] | None = None
    primary_contexts: list[str] | None = None
    provider_account_id: str | None = None
    public_instructions: str | None = None
    metadata: dict | None = None
    last_error: str | None = None
    is_deleted: bool | None = None
    deleted_at: str | None = None
    contribution_means: str | None = None
    allow_public_listing: bool | None = None
    created_at: str | None = None
    updated_at: str | None = None
    credentials_updated_at: str | None = None
    last_tested_at: str | None = None
    last_error_at: str | None = None
    webhooks: list[PaymentWebhookResource] | None = None
    plans: list[PaymentPlanResource] | None = None


@dataclass(frozen=True)
class PaymentMethodCollectionResource:
    """Output DTO for payment methods list."""
    items: list[PaymentMethodResource]
    count: int = 0


@dataclass(frozen=True)
class PublicPaymentMethodResource:
    """Output DTO for public payment method listing."""
    id: str | None = None
    workspace: str | None = None
    provider: str | None = None
    display_name: str | None = None
    status: str | None = None
    provider_account_id: str | None = None
    public_instructions: str | None = None
    metadata: dict | None = None
    allow_public_listing: bool | None = None
    plans: list[PaymentPlanResource] | None = None
