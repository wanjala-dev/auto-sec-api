from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from components.payments.application.mappers.billing_response_mapper import (
    format_invoice_row,
    format_upcoming_invoice,
    summarize_payment_method,
)
from components.payments.application.ports.checkout_context_port import CheckoutContextPort
from components.payments.application.ports.payment_capture_recording_port import (
    PaymentAttemptResolution,
    PaymentCaptureRecordingPort,
)
from components.payments.application.ports.payment_method_credentials_port import (
    PaymentMethodCredentialsPort,
)
from components.payments.application.ports.payment_transaction_store_port import (
    PaymentTransactionStorePort,
)
from components.payments.application.ports.team_plan_billing_port import TeamPlanBillingPort
from components.payments.application.ports.team_plan_payment_setup_port import (
    TeamPlanPaymentSetupPort,
)
from components.payments.application.ports.team_plan_webhook_port import TeamPlanWebhookPort
from components.payments.application.ports.workspace_billing_port import WorkspaceBillingPort
from components.payments.domain.errors import PaymentValidationError


class PaymentServicesFactory:
    """Factory for building payment service instances with provider wiring.

    Centralizes all provider composition to avoid importing providers in controllers.
    """

    @staticmethod
    def build_team_plan_billing_service() -> TeamPlanBillingService:
        """Build TeamPlanBillingService with provider wiring."""
        from components.payments.application.providers.team_plan_billing_provider import (
            TeamPlanBillingProvider,
        )

        return TeamPlanBillingProvider().build_service()

    @staticmethod
    def build_team_plan_webhook_service() -> TeamPlanWebhookService:
        """Build TeamPlanWebhookService with provider wiring."""
        from components.payments.application.providers.team_plan_webhook_provider import (
            TeamPlanWebhookProvider,
        )

        return TeamPlanWebhookProvider().build_service()

    @staticmethod
    def build_workspace_billing_service() -> WorkspaceBillingService:
        """Build WorkspaceBillingService with provider wiring."""
        from components.payments.application.providers.workspace_billing_provider import (
            WorkspaceBillingProvider,
        )

        return WorkspaceBillingProvider().build_service()

    @staticmethod
    def build_payment_method_service() -> PaymentMethodService:
        """Build PaymentMethodService with provider wiring."""
        from components.payments.application.providers.payment_method_provider import (
            PaymentMethodProvider,
        )

        return PaymentMethodProvider().build_service()

    @staticmethod
    def build_payment_runtime_provider() -> Any:
        """Build PaymentRuntimeProvider for webhook verification."""
        from components.payments.application.providers import make_payment_runtime_provider

        return make_payment_runtime_provider()


class TeamPlanBillingService:
    """Application service for workspace team-plan billing mutations."""

    def __init__(
        self,
        billing_store: TeamPlanBillingPort,
        checkout_context: CheckoutContextPort,
    ):
        self.billing_store = billing_store
        self.checkout_context = checkout_context

    def resolve_checkout_context(
        self,
        *,
        workspace: Any,
        team_id: str | None = None,
        user_id: str | None = None,
    ) -> tuple[Any | None, str | None, str | None]:
        """Resolve team, customer email, and customer name for checkout.

        Delegates to the injected CheckoutContextPort to handle ORM lookups,
        keeping this service focused on orchestration rather than infrastructure.

        Returns:
            (team, customer_email, customer_name)
        """
        return self.checkout_context.resolve_checkout_context(
            workspace=workspace,
            team_id=team_id,
            user_id=user_id,
        )

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
    ) -> tuple[dict[str, Any], int]:
        return self.billing_store.checkout_team_plan(
            workspace=workspace,
            plan=plan,
            customer_email=customer_email,
            customer_name=customer_name,
            user_id=user_id,
            team=team,
            success_url=success_url,
            cancel_url=cancel_url,
            proration_behavior=proration_behavior,
        )

    def preview_plan_change(
        self,
        *,
        workspace: Any,
        plan: Any,
    ) -> dict[str, Any] | None:
        return self.billing_store.preview_plan_change(
            workspace=workspace,
            plan=plan,
        )

    def cancel_team_plan(
        self,
        *,
        workspace: Any,
        default_plan: Any | None = None,
    ) -> Any:
        return self.billing_store.cancel_team_plan(
            workspace=workspace,
            default_plan=default_plan,
        )

    def apply_plan_change(
        self,
        *,
        workspace: Any,
        plan: Any,
        proration_behavior: str = "create_prorations",
    ) -> dict[str, Any] | Any | None:
        return self.billing_store.apply_plan_change(
            workspace=workspace,
            plan=plan,
            proration_behavior=proration_behavior,
        )

    def apply_team_plan_purchase(
        self,
        *,
        workspace: Any,
        metadata: dict[str, Any],
        subscription_id: str | None = None,
        customer_id: str | None = None,
        period_end: Any | None = None,
        method: Any | None = None,
    ) -> None:
        self.billing_store.apply_team_plan_purchase(
            workspace=workspace,
            metadata=metadata,
            subscription_id=subscription_id,
            customer_id=customer_id,
            period_end=period_end,
            method=method,
        )

    def sync_deleted_subscription(
        self,
        *,
        workspace: Any,
        default_plan: Any | None = None,
    ) -> Any | None:
        return self.billing_store.sync_deleted_subscription(
            workspace=workspace,
            default_plan=default_plan,
        )


class TeamPlanPaymentSetupService:
    """Application service for managed team-plan payment setup."""

    def __init__(self, setup_store: TeamPlanPaymentSetupPort):
        self.setup_store = setup_store

    def ensure_subscription_payment_method(self, workspace: Any) -> Any:
        return self.setup_store.ensure_subscription_payment_method(workspace=workspace)

    def ensure_platform_customer(
        self,
        workspace: Any,
        *,
        method: Any,
        email: str | None = None,
        name: str | None = None,
    ) -> str:
        return self.setup_store.ensure_platform_customer(
            workspace=workspace,
            method=method,
            email=email,
            name=name,
        )

    def ensure_team_plan_payment_plan(
        self,
        workspace: Any,
        *,
        plan: Any,
        method: Any,
        currency_override: str | None = None,
    ) -> Any | None:
        return self.setup_store.ensure_team_plan_payment_plan(
            workspace=workspace,
            plan=plan,
            method=method,
            currency_override=currency_override,
        )


class TeamPlanWebhookService:
    """Application service for verified Stripe team-plan webhook events."""

    def __init__(self, webhook_store: TeamPlanWebhookPort):
        self.webhook_store = webhook_store

    def handle_verified_webhook(
        self,
        *,
        event: dict[str, Any],
        workspace: Any | None,
        method: Any | None,
        payment_event: Any | None,
        api_key: str | None,
    ) -> None:
        self.webhook_store.handle_verified_webhook(
            event=event,
            workspace=workspace,
            method=method,
            payment_event=payment_event,
            api_key=api_key,
        )


class WorkspaceBillingService:
    """Application service for workspace billing customer and card management."""

    def __init__(self, billing_store: WorkspaceBillingPort):
        self.billing_store = billing_store

    def get_overview(self, *, workspace: Any) -> dict[str, Any]:
        context = self.billing_store.get_context(workspace=workspace)
        customer = self.billing_store.fetch_customer(customer_id=context.customer_id)
        subscription = self.billing_store.fetch_subscription(subscription_id=context.subscription_id)
        default_pm_id = self.billing_store.resolve_default_payment_method_id(
            subscription=subscription,
            customer=customer,
        )
        methods = self.billing_store.list_payment_methods(customer_id=context.customer_id)

        payment_methods = [summarize_payment_method(method, method.get("id") == default_pm_id) for method in methods]

        upcoming_invoice = self.billing_store.preview_upcoming_invoice(
            customer_id=context.customer_id,
            subscription_id=context.subscription_id,
        )
        upcoming_invoice_payload = format_upcoming_invoice(upcoming_invoice)

        return {
            "context": context,
            "subscription": subscription,
            "default_payment_method_id": default_pm_id,
            "payment_methods": payment_methods,
            "upcoming_invoice": upcoming_invoice_payload,
        }

    def get_history(
        self,
        *,
        workspace: Any,
        limit: int,
        starting_after: str | None,
        ending_before: str | None,
    ) -> dict[str, Any]:
        context = self.billing_store.get_context(workspace=workspace)
        invoices, has_more = self.billing_store.list_invoices(
            customer_id=context.customer_id,
            subscription_id=context.subscription_id,
            limit=limit,
            starting_after=starting_after,
            ending_before=ending_before,
        )

        rows = [format_invoice_row(invoice) for invoice in invoices]

        return {
            "context": context,
            "invoices": rows,
            "has_more": has_more,
            "next_cursor": rows[-1]["id"] if has_more and rows else None,
        }

    def list_payment_methods(self, *, workspace: Any) -> dict[str, Any]:
        context = self.billing_store.get_context(workspace=workspace)
        customer = self.billing_store.fetch_customer(customer_id=context.customer_id)
        subscription = self.billing_store.fetch_subscription(subscription_id=context.subscription_id)
        default_pm_id = self.billing_store.resolve_default_payment_method_id(
            subscription=subscription,
            customer=customer,
        )
        methods = self.billing_store.list_payment_methods(customer_id=context.customer_id)
        return {
            "default_payment_method_id": default_pm_id,
            "payment_methods": [
                summarize_payment_method(method, method.get("id") == default_pm_id) for method in methods
            ],
        }

    def create_setup_intent(self, *, workspace: Any) -> dict[str, Any]:
        context = self.billing_store.get_context(workspace=workspace)
        intent = self.billing_store.create_setup_intent(customer_id=context.customer_id)
        return {
            "client_secret": intent.get("client_secret"),
            "customer_id": context.customer_id,
            "publishable_key": self.billing_store.get_publishable_key(),
        }

    def set_default_payment_method(
        self,
        *,
        workspace: Any,
        payment_method_id: str,
    ) -> dict[str, Any]:
        context = self.billing_store.get_context(workspace=workspace)
        payment_method = self.billing_store.retrieve_payment_method(payment_method_id=payment_method_id)
        if payment_method.get("customer") != context.customer_id:
            raise PaymentValidationError("Payment method does not belong to this organization.")

        self.billing_store.set_default_payment_method(
            customer_id=context.customer_id,
            payment_method_id=payment_method_id,
            subscription_id=context.subscription_id,
        )
        return {"status": "ok", "default_payment_method_id": payment_method_id}

    def detach_payment_method(
        self,
        *,
        workspace: Any,
        payment_method_id: str,
    ) -> dict[str, Any]:
        context = self.billing_store.get_context(workspace=workspace)
        customer = self.billing_store.fetch_customer(customer_id=context.customer_id)
        subscription = self.billing_store.fetch_subscription(subscription_id=context.subscription_id)
        default_pm_id = self.billing_store.resolve_default_payment_method_id(
            subscription=subscription,
            customer=customer,
        )
        payment_method = self.billing_store.retrieve_payment_method(payment_method_id=payment_method_id)
        if payment_method.get("customer") != context.customer_id:
            raise PaymentValidationError("Payment method does not belong to this organization.")
        if default_pm_id and default_pm_id == payment_method_id:
            raise PaymentValidationError("Set another default payment method before removing this card.")

        self.billing_store.detach_payment_method(payment_method_id=payment_method_id)
        return {"status": "removed"}


@dataclass(frozen=True)
class PaymentCaptureRecordingResult:
    order: Any | None
    attempt: Any | None


class PaymentCaptureRecordingService:
    def __init__(
        self,
        recording_store: PaymentCaptureRecordingPort,
        payment_transactions: PaymentTransactionStorePort,
        record_successful_payment_use_case,
    ):
        self.recording_store = recording_store
        self.payment_transactions = payment_transactions
        self.record_successful_payment_use_case = record_successful_payment_use_case

    def record_capture(
        self,
        *,
        metadata: dict | None,
        method: Any | None,
        gateway_reference: str,
        gateway_reference_type: str,
        provider: str,
        status: str,
        payment_event: Any | None,
        event_type: str | None,
        external_id: str | None,
        provider_status: str | None,
        amount: Decimal | None,
        currency: str | None,
        payload: dict | None,
        processed_status: str | None = None,
        processed_message: str | None = None,
        update_statuses: bool = True,
    ) -> PaymentCaptureRecordingResult:
        resolution: PaymentAttemptResolution = self.recording_store.resolve_order_attempt(
            metadata=metadata,
            method=method,
        )
        should_finalize_success = update_statuses and status == "succeeded"
        self.recording_store.sync_gateway_reference(
            attempt=resolution.attempt,
            gateway_reference=gateway_reference,
            gateway_reference_type=gateway_reference_type,
        )
        if should_finalize_success:
            self.record_successful_payment_use_case.execute(
                order=resolution.order,
                attempt=resolution.attempt,
                provider=provider,
                payment_event=payment_event,
                event_type=event_type,
                external_id=external_id,
                provider_status=provider_status,
                amount=amount,
                currency=currency,
                payload=payload,
            )
        else:
            self.payment_transactions.record_transaction(
                order=resolution.order,
                attempt=resolution.attempt,
                provider=provider,
                status=status,
                payment_event=payment_event,
                event_type=event_type,
                external_id=external_id,
                provider_status=provider_status,
                amount=amount,
                currency=currency,
                payload=payload,
                update_statuses=update_statuses,
            )
        if processed_status and processed_message:
            self.recording_store.mark_processed(
                payment_event=payment_event,
                status=processed_status,
                message=processed_message,
            )
        return PaymentCaptureRecordingResult(
            order=resolution.order,
            attempt=resolution.attempt,
        )

    def acknowledge_checkout(
        self,
        *,
        metadata: dict | None,
        method: Any | None,
        gateway_reference: str,
        gateway_reference_type: str,
        payment_event: Any | None,
        processed_status: str | None = None,
        processed_message: str | None = None,
    ) -> PaymentCaptureRecordingResult:
        """Acknowledge a Stripe checkout session without capturing a Transaction.

        Used when the checkout session itself represents a handoff (e.g.
        subscription mode — the actual Transaction is created on
        ``invoice.payment_succeeded``, or recipient sponsorship — the
        ingest handler already emitted the payment event). This method
        resolves the PaymentOrder/PaymentAttempt from metadata, stamps
        the gateway reference onto the attempt, and optionally marks
        the PaymentEvent as processed. No PaymentTransaction is recorded.
        """
        resolution: PaymentAttemptResolution = self.recording_store.resolve_order_attempt(
            metadata=metadata,
            method=method,
        )
        self.recording_store.sync_gateway_reference(
            attempt=resolution.attempt,
            gateway_reference=gateway_reference,
            gateway_reference_type=gateway_reference_type,
        )
        if processed_status and processed_message:
            self.recording_store.mark_processed(
                payment_event=payment_event,
                status=processed_status,
                message=processed_message,
            )
        return PaymentCaptureRecordingResult(
            order=resolution.order,
            attempt=resolution.attempt,
        )


class PaymentMethodService:
    """Application service for payment method management."""

    def __init__(
        self,
        credentials_port: PaymentMethodCredentialsPort,
    ):
        from components.payments.application.providers.payment_method_provider import (
            PaymentMethodProvider,
        )

        self._provider = PaymentMethodProvider()
        self.credentials_port = credentials_port

    def set_primary_payment_method(self, **kwargs) -> Any:
        """Set a payment method as primary."""
        use_case = self._provider.build_set_primary_use_case()
        return use_case.execute(**kwargs)

    def start_payment_method_onboarding(self, **kwargs) -> Any:
        """Start payment method onboarding."""
        use_case = self._provider.build_start_onboarding_use_case()
        return use_case.execute(**kwargs)

    def delete_payment_method(self, **kwargs) -> Any:
        """Delete a payment method."""
        use_case = self._provider.build_delete_use_case()
        return use_case.execute(**kwargs)

    def complete_payment_method_onboarding(self, **kwargs) -> Any:
        """Complete payment method onboarding."""
        use_case = self._provider.build_complete_onboarding_use_case()
        return use_case.execute(**kwargs)

    def encrypt_and_save_payment_method_credentials(
        self,
        *,
        method_id: Any,
        credentials: dict[str, Any],
        updated_by_id: Any | None = None,
    ) -> None:
        """Encrypt and persist payment method credentials.

        Delegates to the injected PaymentMethodCredentialsPort to handle ORM
        lookups and credential encryption, keeping this service focused on
        orchestration rather than infrastructure details.
        """
        method = self.credentials_port.get_method(method_id)
        self.credentials_port.write_credentials(method, credentials)
        self.credentials_port.save_method(method, updated_by_id=updated_by_id)


__all__ = [
    "PaymentCaptureRecordingResult",
    "PaymentCaptureRecordingService",
    "PaymentMethodService",
    "PaymentServicesFactory",
    "TeamPlanBillingService",
    "TeamPlanPaymentSetupService",
    "TeamPlanWebhookService",
    "WorkspaceBillingService",
]
