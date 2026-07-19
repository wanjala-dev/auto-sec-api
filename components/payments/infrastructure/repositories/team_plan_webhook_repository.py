from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import stripe
from django.conf import settings

from components.payments.application.ports.payment_transaction_store_port import (
    PaymentTransactionStorePort,
)
from components.payments.application.ports.team_plan_webhook_port import TeamPlanWebhookPort
from components.payments.application.providers.payment_flow_state_provider import (
    PaymentFlowStateProvider,
)
from components.payments.application.providers.team_plan_billing_provider import (
    TeamPlanBillingProvider,
)
from components.payments.application.use_cases.record_successful_payment_use_case import (
    RecordSuccessfulPaymentUseCase,
)
from components.payments.domain.errors import PaymentConfigurationError
from components.payments.infrastructure.adapters.orders import resolve_order_attempt_from_metadata
from components.payments.infrastructure.adapters.payment_event_state import (
    mark_payment_event_processed,
)
from components.payments.infrastructure.adapters.payment_method_credentials import (
    read_payment_method_credentials,
)
from components.payments.infrastructure.adapters.payment_utils import stripe_amount_to_decimal
from components.payments.infrastructure.services.stripe_invoice_helpers import (
    resolve_invoice_subscription_id,
)
from infrastructure.persistence.workspaces.models import Workspace
from infrastructure.persistence.workspaces.payments.models import (
    PaymentEvent,
    PaymentPlan,
    PaymentTransaction,
)

team_plan_billing_service = TeamPlanBillingProvider().build_service()
payment_flow_state_provider = PaymentFlowStateProvider()
mark_payment_flow_requires_action_use_case = payment_flow_state_provider.build_requires_action_use_case()
cancel_payment_flow_use_case = payment_flow_state_provider.build_cancel_use_case()


def _stripe_get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


class TeamPlanWebhookRepository(TeamPlanWebhookPort):
    """Infrastructure adapter for Stripe team-plan webhook processing."""

    def __init__(
        self,
        *,
        payment_transactions: PaymentTransactionStorePort,
        record_successful_payment_use_case: RecordSuccessfulPaymentUseCase,
    ):
        self.payment_transactions = payment_transactions
        self.record_successful_payment_use_case = record_successful_payment_use_case

    def handle_verified_webhook(
        self,
        *,
        event: dict[str, Any],
        workspace: Workspace | None,
        method: Any | None,
        payment_event: PaymentEvent | None,
        api_key: str | None,
    ) -> None:
        # Scope guard: this platform/team billing handler only processes
        # platform-account events. A CONNECT event (one carrying a top-level
        # ``account``) belongs to the donations path and must never be handled
        # here — doing so could mis-book a donor sponsorship invoice as a
        # team-plan payment. Ignore it with no side effects (no PaymentEvent
        # marking, no Stripe calls). Verifier Guard A already prevents such an
        # event from being recorded; this is the matching processing-side
        # guarantee. Legitimate platform events carry no ``account``.
        if isinstance(event, dict) and event.get("account"):
            return

        stripe.api_key = self._resolve_api_key(method=method, api_key=api_key)

        handler = {
            "checkout.session.completed": self._handle_checkout_session_completed,
            "invoice.payment_succeeded": self._handle_invoice_payment_succeeded,
            "invoice.payment_failed": self._handle_invoice_payment_failed,
            "checkout.session.expired": self._handle_checkout_session_expired,
            "customer.subscription.deleted": self._handle_subscription_deleted,
            "customer.subscription.updated": self._handle_subscription_updated,
        }.get(event.get("type"))
        if handler:
            handler(
                event["data"]["object"],
                workspace=workspace,
                method=method,
                payment_event=payment_event,
            )
            if payment_event and not payment_event.processed_at:
                mark_payment_event_processed(
                    payment_event,
                    PaymentEvent.STATUS_PROCESSED,
                    "Stripe team webhook processed.",
                )
            return

        if payment_event:
            mark_payment_event_processed(
                payment_event,
                PaymentEvent.STATUS_IGNORED,
                f"Unhandled Stripe event {event.get('type')}",
            )

    @staticmethod
    def _resolve_api_key(*, method, api_key: str | None) -> str:
        if method:
            credentials = read_payment_method_credentials(method)
            resolved_api_key = credentials.get("secret_key") or api_key or getattr(settings, "STRIPE_SECRET_KEY", None)
        else:
            resolved_api_key = api_key or getattr(settings, "STRIPE_SECRET_KEY", None)
        if not resolved_api_key:
            raise PaymentConfigurationError("Stripe secret key not configured")
        return resolved_api_key

    @staticmethod
    def _to_decimal(amount, currency=None):
        converted = stripe_amount_to_decimal(amount, currency)
        return converted if converted is not None else Decimal("0.00")

    @staticmethod
    def _normalize_currency(currency, default="USD"):
        if not currency:
            return default
        return str(currency).upper()

    @staticmethod
    def _merge_metadata(*sources):
        merged = {}
        for source in sources:
            if not isinstance(source, dict):
                continue
            for key, value in source.items():
                if key not in merged or not merged.get(key):
                    merged[key] = value
        return merged

    @staticmethod
    def _find_workspace(workspace, metadata):
        if workspace:
            return workspace
        return Workspace.objects.filter(id=metadata.get("workspace_id")).first()

    @staticmethod
    def _find_workspace_by_customer(subscription, workspace, metadata):
        resolved_workspace = TeamPlanWebhookRepository._find_workspace(workspace, metadata)
        if resolved_workspace:
            return resolved_workspace
        customer_id = subscription.get("customer")
        if customer_id:
            return Workspace.objects.filter(stripe_customer_id=customer_id).first()
        return None

    @staticmethod
    def _ignore_for_context(context_key, payment_event, event_label: str) -> bool:
        if context_key and context_key != PaymentPlan.CONTEXT_TEAM_PLAN:
            if payment_event:
                mark_payment_event_processed(
                    payment_event,
                    PaymentEvent.STATUS_IGNORED,
                    f"Stripe {event_label} context {context_key} ignored.",
                )
            return True
        return False

    @staticmethod
    def _ignore_missing_workspace(payment_event) -> None:
        if payment_event:
            mark_payment_event_processed(
                payment_event,
                PaymentEvent.STATUS_IGNORED,
                "Missing workspace for Stripe webhook.",
            )

    @staticmethod
    def _extract_period_end(subscription) -> datetime | None:
        if subscription and getattr(subscription, "current_period_end", None):
            return datetime.fromtimestamp(subscription.current_period_end, UTC)
        return None

    @staticmethod
    def _retrieve_subscription(subscription_id: str | None):
        if not subscription_id:
            return None
        # The Stripe SDK already retries transient connection/5xx errors
        # because PaymentsCLIConfig.ready() sets max_network_retries=2 +
        # RequestsClient(timeout=8). Wrapping again with retry_with_backoff
        # adds an extra layer with exponential backoff for any persistent
        # transient class the SDK didn't catch (e.g. RateLimitError).
        from components.payments.application.utils.retry import retry_with_backoff

        try:
            return retry_with_backoff(stripe.Subscription.retrieve, subscription_id)
        except stripe.error.StripeError:
            return None

    @staticmethod
    def _retrieve_payment_intent_metadata(payment_intent_id: str | None) -> dict[str, Any]:
        if not payment_intent_id:
            return {}
        from components.payments.application.utils.retry import retry_with_backoff

        try:
            payment_intent = retry_with_backoff(stripe.PaymentIntent.retrieve, payment_intent_id)
            return payment_intent.get("metadata", {}) or {}
        except stripe.error.StripeError:
            return {}

    def _handle_checkout_session_completed(
        self,
        session,
        *,
        workspace,
        method,
        payment_event=None,
    ) -> None:
        session_metadata = session.get("metadata") or {}
        subscription_id = session.get("subscription")
        subscription = self._retrieve_subscription(subscription_id)
        payment_intent_metadata = self._retrieve_payment_intent_metadata(session.get("payment_intent"))
        subscription_metadata = subscription.get("metadata", {}) if subscription else {}
        metadata = self._merge_metadata(session_metadata, subscription_metadata, payment_intent_metadata)

        context_key = metadata.get("context") or metadata.get("ctx")
        if self._ignore_for_context(context_key, payment_event, "checkout"):
            return

        resolved_workspace = self._find_workspace(workspace, metadata)
        if not resolved_workspace:
            self._ignore_missing_workspace(payment_event)
            return

        amount = self._to_decimal(session.get("amount_total"), session.get("currency"))
        currency = self._normalize_currency(session.get("currency") or "usd")
        order, attempt = resolve_order_attempt_from_metadata(metadata, method=method)
        if attempt and session.get("id") and not attempt.gateway_reference:
            attempt.gateway_reference = session["id"]
            attempt.gateway_reference_type = "checkout_session"
            attempt.save(update_fields=["gateway_reference", "gateway_reference_type", "updated_at"])

        record_status = PaymentTransaction.STATUS_PENDING if subscription_id else PaymentTransaction.STATUS_SUCCEEDED
        if subscription_id:
            self.payment_transactions.record_transaction(
                order=order,
                attempt=attempt,
                provider="stripe",
                status=record_status,
                payment_event=payment_event,
                event_type="checkout.session.completed",
                external_id=session.get("payment_intent") or subscription_id or session.get("id"),
                amount=amount,
                currency=currency,
                payload=session if isinstance(session, dict) else None,
                update_statuses=False,
            )
        else:
            self.record_successful_payment_use_case.execute(
                order=order,
                attempt=attempt,
                provider="stripe",
                payment_event=payment_event,
                event_type="checkout.session.completed",
                external_id=session.get("payment_intent") or session.get("id"),
                amount=amount,
                currency=currency,
                payload=session if isinstance(session, dict) else None,
            )
        team_plan_billing_service.apply_team_plan_purchase(
            workspace=resolved_workspace,
            metadata=metadata,
            subscription_id=subscription_id,
            customer_id=session.get("customer"),
            period_end=self._extract_period_end(subscription),
            method=method,
        )

    def _handle_invoice_payment_succeeded(
        self,
        invoice,
        *,
        workspace,
        method,
        payment_event=None,
    ) -> None:
        subscription_id = resolve_invoice_subscription_id(invoice)
        if not subscription_id:
            if payment_event:
                mark_payment_event_processed(
                    payment_event,
                    PaymentEvent.STATUS_IGNORED,
                    "Stripe invoice missing subscription id.",
                )
            return

        subscription = self._retrieve_subscription(subscription_id)
        payment_intent_metadata = self._retrieve_payment_intent_metadata(invoice.get("payment_intent"))
        subscription_metadata = subscription.get("metadata", {}) if subscription else {}
        metadata = self._merge_metadata(invoice.get("metadata") or {}, subscription_metadata, payment_intent_metadata)

        context_key = metadata.get("context") or metadata.get("ctx")
        if self._ignore_for_context(context_key, payment_event, "invoice"):
            return

        resolved_workspace = self._find_workspace(workspace, metadata)
        if not resolved_workspace:
            self._ignore_missing_workspace(payment_event)
            return

        currency_raw = invoice.get("currency") or "usd"
        amount = self._to_decimal(invoice.get("amount_paid") or invoice.get("amount_due"), currency_raw)
        currency = self._normalize_currency(currency_raw)
        invoice_id = invoice.get("id")

        order, attempt = resolve_order_attempt_from_metadata(metadata, method=method)
        if attempt and invoice_id and not attempt.gateway_reference:
            attempt.gateway_reference = invoice_id
            attempt.gateway_reference_type = "invoice"
            attempt.save(update_fields=["gateway_reference", "gateway_reference_type", "updated_at"])

        self.record_successful_payment_use_case.execute(
            order=order,
            attempt=attempt,
            provider="stripe",
            payment_event=payment_event,
            event_type="invoice.payment_succeeded",
            external_id=invoice_id or subscription_id,
            provider_status=invoice.get("status"),
            amount=amount,
            currency=currency,
            payload=invoice if isinstance(invoice, dict) else None,
        )

        customer_id = invoice.get("customer") or (subscription.customer if subscription else None)
        team_plan_billing_service.apply_team_plan_purchase(
            workspace=resolved_workspace,
            metadata=metadata,
            subscription_id=subscription_id,
            customer_id=customer_id,
            period_end=self._extract_period_end(subscription),
            method=method,
        )

        mark_payment_event_processed(payment_event, PaymentEvent.STATUS_PROCESSED, "Stripe invoice processed.")

    def _handle_invoice_payment_failed(
        self,
        invoice,
        *,
        workspace,
        method,
        payment_event=None,
    ) -> None:
        subscription_id = resolve_invoice_subscription_id(invoice)
        if not subscription_id:
            if payment_event:
                mark_payment_event_processed(
                    payment_event,
                    PaymentEvent.STATUS_IGNORED,
                    "Stripe invoice missing subscription id.",
                )
            return

        subscription = self._retrieve_subscription(subscription_id)
        payment_intent_metadata = self._retrieve_payment_intent_metadata(invoice.get("payment_intent"))
        subscription_metadata = subscription.get("metadata", {}) if subscription else {}
        metadata = self._merge_metadata(invoice.get("metadata") or {}, subscription_metadata, payment_intent_metadata)
        context_key = metadata.get("context") or metadata.get("ctx")
        if self._ignore_for_context(context_key, payment_event, "invoice"):
            return

        resolved_workspace = self._find_workspace(workspace, metadata)
        if not resolved_workspace:
            self._ignore_missing_workspace(payment_event)
            return

        currency_raw = invoice.get("currency") or "usd"
        amount = self._to_decimal(invoice.get("amount_due") or invoice.get("amount_remaining"), currency_raw)
        currency = self._normalize_currency(currency_raw)
        invoice_id = invoice.get("id")

        order, attempt = resolve_order_attempt_from_metadata(metadata, method=method)
        self.payment_transactions.record_transaction(
            order=order,
            attempt=attempt,
            provider="stripe",
            status=PaymentTransaction.STATUS_FAILED,
            payment_event=payment_event,
            event_type="invoice.payment_failed",
            external_id=invoice_id or subscription_id,
            provider_status=invoice.get("status"),
            amount=amount,
            currency=currency,
            payload=invoice if isinstance(invoice, dict) else None,
            update_statuses=False,
        )

        mark_payment_flow_requires_action_use_case.execute(
            order=order,
            attempt=attempt,
            message="Stripe invoice payment failed.",
        )

    def _handle_checkout_session_expired(
        self,
        session,
        *,
        workspace,
        method,
        payment_event=None,
    ) -> None:
        metadata = session.get("metadata") or {}
        context_key = metadata.get("context") or metadata.get("ctx")
        if self._ignore_for_context(context_key, payment_event, "checkout"):
            return

        order, attempt = resolve_order_attempt_from_metadata(metadata, method=method)
        self.payment_transactions.record_transaction(
            order=order,
            attempt=attempt,
            provider="stripe",
            status=PaymentTransaction.STATUS_IGNORED,
            payment_event=payment_event,
            event_type="checkout.session.expired",
            external_id=session.get("id"),
            payload=session if isinstance(session, dict) else None,
            update_statuses=False,
        )
        cancel_payment_flow_use_case.execute(
            order=order,
            attempt=attempt,
            message="Stripe checkout session expired.",
        )

    def _handle_subscription_deleted(
        self,
        subscription,
        *,
        workspace,
        method,
        payment_event=None,
    ) -> None:
        metadata = subscription.get("metadata") or {}
        context_key = metadata.get("context") or metadata.get("ctx")
        if self._ignore_for_context(context_key, payment_event, "subscription"):
            return

        resolved_workspace = self._find_workspace(workspace, metadata)
        if not resolved_workspace:
            self._ignore_missing_workspace(payment_event)
            return

        subscription_id = subscription.get("id")
        order, attempt = resolve_order_attempt_from_metadata(metadata, method=method)
        self.payment_transactions.record_transaction(
            order=order,
            attempt=attempt,
            provider="stripe",
            status=PaymentTransaction.STATUS_IGNORED,
            payment_event=payment_event,
            event_type="customer.subscription.deleted",
            external_id=subscription_id,
            provider_status=subscription.get("status"),
            payload=subscription if isinstance(subscription, dict) else None,
            update_statuses=False,
        )

        cancel_payment_flow_use_case.execute(
            order=order,
            attempt=attempt,
            message="Stripe subscription canceled.",
        )
        team_plan_billing_service.sync_deleted_subscription(workspace=resolved_workspace)

    def _handle_subscription_updated(
        self,
        subscription,
        *,
        workspace,
        method,
        payment_event=None,
    ) -> None:
        metadata = subscription.get("metadata") or {}
        context_key = metadata.get("context") or metadata.get("ctx")
        if self._ignore_for_context(context_key, payment_event, "subscription"):
            return

        resolved_workspace = self._find_workspace_by_customer(subscription, workspace, metadata)
        if not resolved_workspace:
            self._ignore_missing_workspace(payment_event)
            return

        items = (subscription.get("items") or {}).get("data") or []
        price_id = None
        if items:
            price_id = (items[0].get("price") or {}).get("id")

        if price_id and not metadata.get("team_plan_id"):
            payment_plan = PaymentPlan.objects.filter(
                price_id=price_id,
                context=PaymentPlan.CONTEXT_TEAM_PLAN,
            ).first()
            if payment_plan:
                metadata = metadata.copy()
                metadata.setdefault("plan_id", str(payment_plan.id))
                team_plan_id = (payment_plan.metadata or {}).get("team_plan_id")
                if team_plan_id:
                    metadata.setdefault("team_plan_id", team_plan_id)

        order, attempt = resolve_order_attempt_from_metadata(metadata, method=method)
        self.payment_transactions.record_transaction(
            order=order,
            attempt=attempt,
            provider="stripe",
            status=PaymentTransaction.STATUS_IGNORED,
            payment_event=payment_event,
            event_type="customer.subscription.updated",
            external_id=subscription.get("id"),
            provider_status=subscription.get("status"),
            payload=subscription if isinstance(subscription, dict) else None,
            update_statuses=False,
        )

        team_plan_billing_service.apply_team_plan_purchase(
            workspace=resolved_workspace,
            metadata=metadata,
            subscription_id=subscription.get("id"),
            customer_id=subscription.get("customer"),
            period_end=self._extract_period_end(subscription),
            method=method,
        )

        mark_payment_event_processed(payment_event, PaymentEvent.STATUS_PROCESSED, "Stripe subscription updated.")
