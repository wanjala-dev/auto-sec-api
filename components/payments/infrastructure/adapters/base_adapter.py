from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal

from django.http import HttpRequest

from infrastructure.persistence.workspaces.payments.models import WorkspacePaymentMethod


@dataclass
class WebhookVerificationResult:
    event: object
    method: WorkspacePaymentMethod | None
    workspace: object | None
    account_id: str | None
    api_key: str | None
    legacy_context: object | None = None


class PaymentAdapter:
    slug: str

    def verify_webhook(
        self,
        request: HttpRequest,
        endpoint_name: str | None,
        candidate_methods: Iterable[WorkspacePaymentMethod],
    ) -> WebhookVerificationResult:
        raise NotImplementedError

    def create_checkout_session(
        self,
        method: WorkspacePaymentMethod,
        plan,
        *,
        amount,
        currency: str,
        success_url: str,
        cancel_url: str,
        customer_email: str | None,
        customer_id: str | None = None,
        client_reference_id: str | None,
        metadata: dict | None,
        idempotency_key: str | None = None,
        donor_tip=None,
    ):
        raise NotImplementedError

    def ensure_plan_resources(self, method: WorkspacePaymentMethod, plan) -> None:
        raise NotImplementedError

    def capture_payment(
        self,
        method: WorkspacePaymentMethod,
        identifier: str,
        *,
        amount: Decimal | None = None,
        currency: str = "usd",
        metadata: dict | None = None,
    ) -> dict:
        raise NotImplementedError
