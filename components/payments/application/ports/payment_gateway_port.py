from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID


@dataclass(frozen=True)
class VerifiedWebhook:
    provider: str
    provider_event_id: str
    event_type: str
    account_id: str | None = None
    workspace_id: UUID | None = None
    method_id: UUID | None = None
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CheckoutSession:
    provider: str
    checkout_id: str
    redirect_url: str
    metadata: dict[str, Any] = field(default_factory=dict)


class PaymentGatewayPort(Protocol):
    def verify_webhook(
        self,
        *,
        endpoint_name: str | None,
        payload: bytes,
        headers: dict[str, str],
        query_params: dict[str, str],
    ) -> VerifiedWebhook: ...

    def create_checkout_session(
        self,
        *,
        method_id: UUID,
        context: str,
        amount: Decimal | None,
        currency: str,
        success_url: str,
        cancel_url: str,
        customer_email: str | None,
        customer_id: str | None,
        client_reference_id: str | None,
        metadata: dict[str, Any],
    ) -> CheckoutSession: ...

    def list_customer_payment_methods(
        self,
        *,
        customer_id: str,
        method_type: str = "card",
        limit: int = 10,
        stripe_account: str | None = None,
    ) -> list[dict[str, Any]]:
        """List saved payment methods for a customer."""
        ...

    def retrieve_payment_method(
        self,
        *,
        payment_method_id: str,
    ) -> dict[str, Any]:
        """Retrieve a payment method's details (including its customer)."""
        ...

    def detach_payment_method(
        self,
        *,
        payment_method_id: str,
    ) -> dict[str, Any]:
        """Detach a payment method from its customer."""
        ...

    def set_default_payment_method(
        self,
        *,
        customer_id: str,
        payment_method_id: str,
        stripe_account: str | None = None,
    ) -> dict[str, Any]:
        """Set a payment method as the customer's default."""
        ...

    def retrieve_customer(
        self,
        *,
        customer_id: str,
        stripe_account: str | None = None,
    ) -> dict[str, Any]:
        """Retrieve a customer from the payment provider."""
        ...

    def create_customer(
        self,
        *,
        email: str,
        name: str | None = None,
        stripe_account: str | None = None,
    ) -> dict[str, Any]:
        """Create a customer on the payment provider."""
        ...

    def create_setup_intent(
        self,
        *,
        customer_id: str,
        payment_method_types: list[str] | None = None,
    ) -> dict[str, Any]:
        """Create a setup intent to save a payment method."""
        ...

    def verify_account(
        self,
        *,
        api_key: str,
        account_id: str | None = None,
    ) -> dict[str, Any]:
        """Verify that payment provider credentials are valid."""
        ...

    def register_webhook_endpoint(
        self,
        *,
        url: str,
        enabled_events: list[str],
        api_key: str,
        description: str = "",
        connect: bool = False,
    ) -> dict[str, Any]:
        """Register a webhook endpoint with the payment provider."""
        ...

    def issue_refund(
        self,
        *,
        external_charge_id: str,
        amount: Decimal | None,
        currency: str,
        reason: str,
        idempotency_key: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Issue a refund for a previously captured payment.

        Args:
            external_charge_id: The provider's charge/payment_intent ID.
            amount: Refund amount (None = full refund).
            currency: ISO currency code.
            reason: One of requested_by_customer, duplicate, fraudulent.
            idempotency_key: Prevents duplicate refunds on retry.
            metadata: Optional provider metadata.

        Returns:
            Provider response dict with at minimum ``{"id": "...", "status": "..."}``.
        """
        ...
