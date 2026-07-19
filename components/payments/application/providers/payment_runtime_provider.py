from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from components.payments.application.providers.payment_gateway_provider import (
    make_payment_gateway_provider,
)
from components.payments.application.use_cases.attach_provider_attempt_reference_use_case import (
    AttachProviderAttemptReferenceUseCase,
)
from components.payments.application.use_cases.create_checkout_session_use_case import (
    CreateCheckoutSessionUseCase,
)
from components.payments.application.use_cases.create_payment_order_use_case import (
    CreatePaymentOrderUseCase,
)
from components.payments.application.use_cases.mark_checkout_failed_use_case import (
    MarkCheckoutFailedUseCase,
)
from components.payments.application.use_cases.resolve_payment_method_and_plan_use_case import (
    ResolvePaymentMethodAndPlanUseCase,
)
from components.payments.application.ports.payment_gateway_provider_port import (
    PaymentGatewayProviderPort,
)
from components.payments.application.ports.payment_method_selection_port import (
    PaymentMethodSelectionPort,
)
from components.payments.application.ports.payment_order_store_port import PaymentOrderStorePort
from components.payments.application.ports.payment_plan_store_port import PaymentPlanStorePort

if TYPE_CHECKING:
    pass


@dataclass(frozen=True)
class VerifiedPaymentWebhookResult:
    event: Any
    method: Any | None
    workspace: Any | None
    account_id: str | None
    legacy_context: object | None
    provider_slug: str
    payment_event: Any | None
    payment_event_duplicate: bool
    payment_event_processable: bool
    api_key: str | None


class PaymentRuntimeProvider:
    """Application-level composition for payment method resolution, checkout, and webhook verification."""

    def __init__(
        self,
        *,
        gateway_provider: PaymentGatewayProviderPort | None = None,
        payment_method_selection: PaymentMethodSelectionPort | None = None,
        payment_plans: PaymentPlanStorePort | None = None,
        payment_orders: PaymentOrderStorePort | None = None,
        webhook_verifier: Any | None = None,
    ):
        self._gateway_provider = gateway_provider
        self._payment_method_selection = payment_method_selection
        self._payment_plans = payment_plans
        self._payment_orders = payment_orders
        self._webhook_verifier = webhook_verifier

    @property
    def gateway_provider(self) -> PaymentGatewayProviderPort:
        if self._gateway_provider is None:
            self._gateway_provider = make_payment_gateway_provider()
        return self._gateway_provider

    @property
    def payment_method_selection(self) -> PaymentMethodSelectionPort:
        if self._payment_method_selection is None:
            self._payment_method_selection = self._build_payment_method_selection()
        return self._payment_method_selection

    @property
    def payment_orders(self) -> PaymentOrderStorePort:
        if self._payment_orders is None:
            self._payment_orders = self._build_payment_order_store()
        return self._payment_orders

    @property
    def payment_plans(self) -> PaymentPlanStorePort:
        if self._payment_plans is None:
            self._payment_plans = self._build_payment_plan_store()
        return self._payment_plans

    @property
    def webhook_verifier(self) -> Any:
        if self._webhook_verifier is None:
            self._webhook_verifier = self._build_webhook_verifier()
        return self._webhook_verifier

    @staticmethod
    def _build_payment_method_selection() -> PaymentMethodSelectionPort:
        from components.payments.infrastructure.repositories.orm_payment_method_selection_repository import (
            OrmPaymentMethodSelectionRepository,
        )

        return OrmPaymentMethodSelectionRepository()

    @staticmethod
    def _build_payment_order_store() -> PaymentOrderStorePort:
        from components.payments.infrastructure.repositories.orm_payment_order_repository import (
            OrmPaymentOrderRepository,
        )

        return OrmPaymentOrderRepository()

    @staticmethod
    def _build_payment_plan_store() -> PaymentPlanStorePort:
        from components.payments.infrastructure.repositories.orm_payment_plan_repository import (
            OrmPaymentPlanRepository,
        )

        return OrmPaymentPlanRepository()

    @staticmethod
    def _build_webhook_verifier() -> Any:
        from components.payments.infrastructure.adapters.webhook_verifier import (
            LegacyIncomingWebhookVerifier,
        )

        return LegacyIncomingWebhookVerifier()

    def resolve_method_and_plan(
        self,
        *,
        workspace: Any,
        context: str,
        payment_method_id: str | None = None,
        plan_slug: str | None = None,
        recipient: Any | None = None,
        prefer_recurring: bool | None = None,
    ) -> tuple[Any | None, Any | None]:
        return ResolvePaymentMethodAndPlanUseCase(
            self.payment_method_selection,
            self.payment_plans,
        ).execute(
            workspace=workspace,
            context=context,
            payment_method_id=payment_method_id,
            plan_slug=plan_slug,
            recipient=recipient,
            prefer_recurring=prefer_recurring,
        )

    def create_checkout_session(
        self,
        method: Any,
        plan: Any | None,
        *,
        amount: Decimal | None,
        currency: str,
        success_url: str,
        cancel_url: str,
        customer_email: str | None,
        customer_id: str | None = None,
        client_reference_id: str | None,
        metadata: dict[str, str] | None = None,
        context: str = "general",
        donor_tip=None,
    ) -> object:
        gateway = self.gateway_provider.get_gateway_for_provider(method.provider.slug)

        checkout_metadata = dict(metadata or {})
        checkout_metadata.setdefault("ctx", context)
        result = CreateCheckoutSessionUseCase(
            create_payment_order=CreatePaymentOrderUseCase(self.payment_orders),
            mark_checkout_failed=MarkCheckoutFailedUseCase(self.payment_orders),
            attach_provider_attempt_reference=AttachProviderAttemptReferenceUseCase(
                self.payment_orders
            ),
        ).execute(
            gateway=gateway,
            method=method,
            plan=plan,
            context=context,
            amount=amount,
            currency=currency,
            success_url=success_url,
            cancel_url=cancel_url,
            customer_email=customer_email,
            customer_id=customer_id,
            client_reference_id=client_reference_id,
            metadata=checkout_metadata,
            customer_name=checkout_metadata.get("name"),
            donor_tip=donor_tip,
        )
        checkout = result.checkout_payload
        if isinstance(checkout, dict):
            checkout.setdefault("orderId", str(result.order_id))
            checkout.setdefault("attemptId", str(result.attempt_id))
        return checkout

    def verify_webhook(
        self,
        request: Any,
        endpoint_name: str | None = None,
    ) -> VerifiedPaymentWebhookResult:
        result = self.webhook_verifier.verify(request, endpoint_name)
        return VerifiedPaymentWebhookResult(
            event=result.event,
            method=result.method,
            workspace=result.workspace,
            account_id=result.account_id,
            legacy_context=result.legacy_context,
            provider_slug=result.provider_slug,
            payment_event=result.payment_event,
            payment_event_duplicate=result.payment_event_duplicate,
            payment_event_processable=result.payment_event_processable,
            api_key=result.api_key,
        )


def make_payment_runtime_provider() -> PaymentRuntimeProvider:
    return PaymentRuntimeProvider()
