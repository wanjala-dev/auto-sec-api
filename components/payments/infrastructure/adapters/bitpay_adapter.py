from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from decimal import Decimal

import requests
from django.core.exceptions import ImproperlyConfigured
from django.http import HttpRequest

from components.payments.infrastructure.adapters.base_adapter import PaymentAdapter, WebhookVerificationResult
from components.payments.infrastructure.adapters.payment_method_credentials import (
    read_payment_method_credentials,
)
from infrastructure.persistence.workspaces.payments.models import PaymentWebhookEndpoint, WorkspacePaymentMethod

logger = logging.getLogger(__name__)


class BitpayPaymentAdapter(PaymentAdapter):
    slug = "bitpay"

    def _get_credentials(self, method: WorkspacePaymentMethod | None):
        creds = (read_payment_method_credentials(method) if method else {}) or {}
        token = creds.get("api_token") or creds.get("token")
        if not token:
            raise ImproperlyConfigured("BitPay payment method missing api_token.")
        environment = (creds.get("environment") or "test").lower()
        base_url = creds.get("base_url")
        if not base_url:
            base_url = (
                "https://bitpay.com"
                if environment in {"prod", "production", "live"}
                else "https://test.bitpay.com"
            )
        return token, base_url.rstrip("/"), creds

    def _default_headers(self, token: str) -> dict:
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _parse_body(self, request: HttpRequest) -> dict:
        try:
            raw = request.body.decode("utf-8")
        except Exception:
            raw = ""
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Unable to parse BitPay webhook payload: %s", raw[:200])
            return {}

    # ------------------------------------------------------------------ Adapter API
    def verify_webhook(
        self,
        request: HttpRequest,
        endpoint_name: str | None,
        candidate_methods: Iterable[WorkspacePaymentMethod],
    ) -> WebhookVerificationResult:
        payload = self._parse_body(request)
        token = (
            payload.get("token")
            or payload.get("event", {}).get("token")
            or payload.get("data", {}).get("token")
        )
        if not token:
            raise ValueError("BitPay webhook missing token.")

        for method in candidate_methods:
            webhooks = method.webhooks.filter(
                status=PaymentWebhookEndpoint.STATUS_ACTIVE,
            )
            if endpoint_name:
                webhooks = webhooks.filter(name=endpoint_name)
            for webhook in webhooks:
                if webhook.signing_secret and webhook.signing_secret == token:
                    return WebhookVerificationResult(
                        event=payload,
                        method=method,
                        workspace=method.workspace,
                        account_id=None,
                        api_key=None,
                    )

        raise ValueError("Unable to verify BitPay webhook payload.")

    def create_checkout_session(
        self,
        method: WorkspacePaymentMethod,
        plan,
        *,
        amount: Decimal | None,
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
        del idempotency_key
        del customer_id
        if donor_tip is not None and getattr(donor_tip, "is_active", False):
            raise ImproperlyConfigured("Donor tips are not supported for the BitPay provider.")
        token, base_url, creds = self._get_credentials(method)
        invoice_currency = (currency or plan.currency if plan else "usd").upper()
        invoice_amount = (
            Decimal(amount)
            if amount is not None
            else Decimal(plan.amount) if plan and plan.amount else None
        )
        if invoice_amount is None or invoice_amount <= 0:
            raise ImproperlyConfigured("BitPay checkout requires a positive amount.")

        invoice_payload = {
            "price": float(invoice_amount),
            "currency": invoice_currency,
            "redirectURL": success_url,
            "closeURL": cancel_url,
            "notificationEmail": creds.get("notification_email", ""),
            "itemDesc": (plan.label if plan else method.display_name),
            "extendedNotifications": True,
        }

        webhooks = method.webhooks.filter(status=PaymentWebhookEndpoint.STATUS_ACTIVE)
        webhook = webhooks.first()
        if webhook and webhook.url:
            invoice_payload["notificationURL"] = webhook.url

        if customer_email:
            invoice_payload["buyerEmail"] = customer_email
        metadata = metadata or {}
        metadata.setdefault("method_id", str(method.id))
        metadata.setdefault("workspace_id", str(method.workspace_id))
        metadata.setdefault("ctx", metadata.get("ctx") or metadata.get("context"))
        try:
            invoice_payload["posData"] = json.dumps(metadata, separators=(",", ":"))
        except (TypeError, ValueError):
            safe_meta = {
                key: str(value) for key, value in metadata.items() if value is not None
            }
            invoice_payload["posData"] = json.dumps(safe_meta, separators=(",", ":"))

        if client_reference_id:
            invoice_payload["orderId"] = client_reference_id

        try:
            response = requests.post(
                f"{base_url}/invoices",
                headers=self._default_headers(token),
                json=invoice_payload,
                timeout=30,
            )
            response.raise_for_status()
        except requests.RequestException as exc:  # pragma: no cover - network failure
            logger.exception("BitPay invoice creation failed: %s", exc)
            raise ValueError("Unable to create BitPay invoice.") from exc

        body = response.json()
        invoice = body.get("data") or body
        checkout_url = invoice.get("url") or invoice.get("paymentUrl")

        return {
            "provider": "bitpay",
            "invoiceId": invoice.get("id"),
            "checkoutUrl": checkout_url,
            "status": invoice.get("status"),
            "currency": invoice.get("currency"),
            "expiresAt": invoice.get("expirationTime"),
            "invoice": invoice,
        }

    def ensure_plan_resources(self, method: WorkspacePaymentMethod, plan) -> None:
        # BitPay does not provision recurring plans ahead of time; invoices are per checkout.
        return

    def capture_payment(
        self,
        method: WorkspacePaymentMethod,
        identifier: str,
        *,
        amount: Decimal | None = None,
        currency: str = "usd",
        metadata: dict | None = None,
    ) -> dict:
        raise NotImplementedError("BitPay payments settle asynchronously via invoices.")
