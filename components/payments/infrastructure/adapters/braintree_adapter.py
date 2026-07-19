from __future__ import annotations

import json
from collections.abc import Iterable
from decimal import Decimal

import braintree
from django.core.exceptions import ImproperlyConfigured
from django.http import HttpRequest

from components.payments.infrastructure.adapters.base_adapter import PaymentAdapter, WebhookVerificationResult
from components.payments.infrastructure.adapters.payment_method_credentials import (
    read_payment_method_credentials,
)
from infrastructure.persistence.workspaces.payments.models import PaymentPlan, WorkspacePaymentMethod


class BraintreePaymentAdapter(PaymentAdapter):
    slug = "braintree"

    # ------------------------------------------------------------------
    # Helpers
    def _get_credentials(self, method: WorkspacePaymentMethod | None) -> dict:
        credentials = (read_payment_method_credentials(method) if method else {}) or {}
        merchant_id = credentials.get("merchant_id")
        public_key = credentials.get("public_key")
        private_key = credentials.get("private_key")
        merchant_account_id = credentials.get("merchant_account_id")
        venmo_merchant_account_id = credentials.get("venmo_merchant_account_id")
        environment_name = (credentials.get("environment") or "sandbox").lower()
        if not merchant_id or not public_key or not private_key:
            raise ImproperlyConfigured(
                "Braintree credentials require merchant_id, public_key, and private_key."
            )

        environment = braintree.Environment.Sandbox
        if environment_name in ("production", "prod", "live"):
            environment = braintree.Environment.Production

        return {
            "merchant_id": merchant_id,
            "public_key": public_key,
            "private_key": private_key,
            "merchant_account_id": merchant_account_id,
            "venmo_merchant_account_id": venmo_merchant_account_id,
            "environment": environment,
        }

    def _gateway(self, method: WorkspacePaymentMethod | None):
        creds = self._get_credentials(method)
        # 8s network timeout matches the Stripe adapter and stays well under
        # Braintree's webhook delivery budget. Default is unbounded.
        gateway = braintree.BraintreeGateway(
            braintree.Configuration(
                environment=creds["environment"],
                merchant_id=creds["merchant_id"],
                public_key=creds["public_key"],
                private_key=creds["private_key"],
                timeout=8,
            )
        )
        return gateway, creds

    def _resolve_merchant_account_id(
        self, method: WorkspacePaymentMethod, creds: dict, currency: str
    ) -> str | None:
        metadata = method.metadata or {}
        # Allow overrides via metadata or credentials.
        merchant_account_id = (
            metadata.get("merchant_account_id")
            or creds.get("merchant_account_id")
            or None
        )
        if not merchant_account_id:
            return None
        # Optionally support currency-specific mapping in metadata.
        if isinstance(merchant_account_id, dict):
            return merchant_account_id.get(currency.lower()) or merchant_account_id.get(
                currency.upper()
            )
        return merchant_account_id

    def _serialize_notification(self, notification: braintree.WebhookNotification) -> dict:
        payload = {
            "id": getattr(notification, "id", None),
            "kind": notification.kind,
            "timestamp": notification.timestamp.isoformat()
            if getattr(notification, "timestamp", None)
            else None,
            "merchant_account_id": getattr(notification, "merchant_account_id", None),
            "source_merchant_id": getattr(notification, "source_merchant_id", None),
        }

        transaction = getattr(notification, "transaction", None)
        metadata = {}
        if transaction:
            payload["transaction"] = {
                "id": getattr(transaction, "id", None),
                "status": getattr(transaction, "status", None),
                "amount": str(getattr(transaction, "amount", "")),
                "currency": getattr(transaction, "currency_iso_code", None),
                "payment_instrument_type": getattr(
                    transaction, "payment_instrument_type", None
                ),
                "order_id": getattr(transaction, "order_id", None),
            }
            order_id_payload = getattr(transaction, "order_id", "") or ""
            if order_id_payload:
                try:
                    metadata = json.loads(order_id_payload)
                except json.JSONDecodeError:
                    metadata = {}

        subscription = getattr(notification, "subscription", None)
        if subscription:
            payload["subscription"] = {
                "id": getattr(subscription, "id", None),
                "status": getattr(subscription, "status", None),
                "billing_period_start_date": getattr(
                    subscription, "billing_period_start_date", None
                ),
                "billing_period_end_date": getattr(
                    subscription, "billing_period_end_date", None
                ),
            }

        payload["metadata"] = metadata
        return payload

    # ------------------------------------------------------------------
    # Adapter interface
    def verify_webhook(
        self,
        request: HttpRequest,
        endpoint_name: str | None,
        candidate_methods: Iterable[WorkspacePaymentMethod],
    ) -> WebhookVerificationResult:
        signature = request.POST.get("bt_signature") or request.GET.get("bt_signature")
        payload = request.POST.get("bt_payload") or request.GET.get("bt_payload")

        if not signature or not payload:
            raise ValueError("Missing Braintree webhook signature or payload.")

        # Attempt verification per configured payment method.
        for method in candidate_methods:
            try:
                gateway, creds = self._gateway(method)
            except ImproperlyConfigured:
                continue

            try:
                notification = gateway.webhook_notification.parse(signature, payload)
            except braintree.exceptions.InvalidSignatureError:
                continue

            event_payload = self._serialize_notification(notification)
            event_payload["raw_notification"] = notification

            return WebhookVerificationResult(
                event=event_payload,
                method=method,
                workspace=method.workspace,
                account_id=event_payload.get("merchant_account_id")
                or creds.get("merchant_account_id"),
                api_key=None,
            )

        # Fallback to global credentials if available.
        try:
            gateway, creds = self._gateway(None)
        except ImproperlyConfigured as exc:
            raise ValueError("Unable to verify Braintree webhook.") from exc

        try:
            notification = gateway.webhook_notification.parse(signature, payload)
        except braintree.exceptions.InvalidSignatureError as exc:
            raise ValueError("Unable to verify Braintree webhook.") from exc

        event_payload = self._serialize_notification(notification)
        event_payload["raw_notification"] = notification

        return WebhookVerificationResult(
            event=event_payload,
            method=None,
            workspace=None,
            account_id=event_payload.get("merchant_account_id")
            or creds.get("merchant_account_id"),
            api_key=None,
        )

    def create_checkout_session(
        self,
        method: WorkspacePaymentMethod,
        plan: PaymentPlan | None,
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
        del success_url, cancel_url, client_reference_id, idempotency_key, customer_id  # Unused for Braintree token generation.
        if donor_tip is not None and getattr(donor_tip, "is_active", False):
            raise ImproperlyConfigured("Donor tips are not supported for the Braintree provider.")
        gateway, creds = self._gateway(method)

        currency = (currency or "usd").lower()
        metadata = metadata or {}
        metadata.setdefault("method_id", str(method.id))
        metadata.setdefault("mid", str(method.id))
        metadata.setdefault("workspace_id", str(method.workspace_id))
        metadata.setdefault("sid", str(method.workspace_id))

        decimal_amount = (
            Decimal(amount)
            if amount is not None
            else (Decimal(plan.amount) if plan else None)
        )
        if decimal_amount is None:
            raise ImproperlyConfigured(
                "Braintree checkout requires an explicit amount or a payment plan."
            )

        merchant_account_id = self._resolve_merchant_account_id(method, creds, currency)
        venmo_account_id = (
            method.metadata or {}
        ).get("venmo_merchant_account_id") or creds.get("venmo_merchant_account_id")

        token_params = {}
        if merchant_account_id:
            token_params["merchant_account_id"] = merchant_account_id

        if customer_email:
            # Using customer email as identifier hints Braintree to reuse vaulted customers.
            token_params["customer_id"] = customer_email

        client_token = gateway.client_token.generate(token_params)

        return {
            "provider": "braintree",
            "clientToken": client_token,
            "amount": f"{decimal_amount:.2f}",
            "currency": currency.upper(),
            "merchantAccountId": merchant_account_id,
            "venmoMerchantAccountId": venmo_account_id,
            "metadata": metadata,
            "methodId": str(method.id),
            "seedId": str(method.workspace_id),
        }

    def ensure_plan_resources(
        self,
        method: WorkspacePaymentMethod,
        plan: PaymentPlan,
    ) -> None:
        # Braintree plans/transactions are handled per-charge; nothing to provision ahead of time.
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
        if not identifier:
            raise ValueError("Braintree capture requires a payment method nonce.")

        metadata = metadata or {}
        metadata.setdefault("method_id", str(method.id))
        metadata.setdefault("workspace_id", str(method.workspace_id))
        currency = (currency or "usd").lower()

        gateway, creds = self._gateway(method)
        merchant_account_id = (
            metadata.get("merchant_account_id")
            or self._resolve_merchant_account_id(method, creds, currency)
        )

        decimal_amount = Decimal(amount) if amount is not None else None
        if decimal_amount is None:
            raise ValueError("Braintree capture requires an amount.")

        sale_kwargs = {
            "amount": f"{decimal_amount:.2f}",
            "payment_method_nonce": identifier,
            "options": {"submit_for_settlement": True},
        }
        if merchant_account_id:
            sale_kwargs["merchant_account_id"] = merchant_account_id

        order_metadata_keys = [
            "order_id",
            "attempt_id",
            "ctx",
            "context",
            "workspace_id",
            "sid",
            "method_id",
            "mid",
            "cid",
            "recipient_id",
            "plan",
            "plan_slug",
            "freq",
            "payment_frequency",
            "campaign_id",
            "cam",
            "name",
            "email",
        ]
        order_metadata = {
            key: metadata.get(key)
            for key in order_metadata_keys
            if metadata.get(key)
        }
        if order_metadata:
            order_payload = json.dumps(order_metadata, separators=(",", ":"))
            if len(order_payload) <= 255:
                sale_kwargs["order_id"] = order_payload
            else:
                minimal_payload = json.dumps(
                    {key: order_metadata.get(key) for key in ("order_id", "attempt_id") if order_metadata.get(key)},
                    separators=(",", ":"),
                )
                if len(minimal_payload) <= 255:
                    sale_kwargs["order_id"] = minimal_payload

        customer_kwargs = {}
        email = metadata.get("email")
        if email:
            customer_kwargs["email"] = email
        name = metadata.get("name") or ""
        name_parts = name.split(" ", 1)
        first_name = metadata.get("first_name") or (name_parts[0] if name_parts else "")
        last_name = metadata.get("last_name") or (
            name_parts[1] if len(name_parts) > 1 else ""
        )
        if first_name:
            customer_kwargs["first_name"] = first_name
        if last_name:
            customer_kwargs["last_name"] = last_name
        if customer_kwargs:
            sale_kwargs["customer"] = customer_kwargs

        result = gateway.transaction.sale(sale_kwargs)
        if not result.is_success:
            message = result.message or "Braintree transaction failed."
            deep_errors = result.errors.deep_errors if hasattr(result.errors, "deep_errors") else []
            if deep_errors:
                message = "; ".join(error.message for error in deep_errors) or message
            raise ValueError(message)

        transaction = result.transaction
        amount_decimal = Decimal(str(transaction.amount))
        payer = {
            "email": transaction.customer_details.email,
            "first_name": transaction.customer_details.first_name,
            "last_name": transaction.customer_details.last_name,
            "customer_id": transaction.customer_details.id,
        }

        return {
            "metadata": metadata,
            "amount": amount_decimal,
            "currency": transaction.currency_iso_code or currency.upper(),
            "payer": payer,
            "transaction": {
                "id": transaction.id,
                "status": transaction.status,
                "payment_instrument_type": transaction.payment_instrument_type,
                "created_at": transaction.created_at.isoformat()
                if getattr(transaction, "created_at", None)
                else None,
            },
        }
