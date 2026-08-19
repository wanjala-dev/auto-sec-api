from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from components.payments.application.ports.payment_gateway_provider_port import (
    PaymentGatewayProviderPort,
)
from components.payments.application.ports.payment_method_selection_port import (
    PaymentMethodSelectionPort,
)
from components.payments.application.ports.payment_order_store_port import PaymentOrderStorePort
from components.payments.application.ports.payment_plan_store_port import PaymentPlanStorePort
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

if TYPE_CHECKING:
    pass


@dataclass(frozen=True)
class VerifiedPaymentWebhookResult:
    """Outcome of signature verification — reads only, nothing recorded yet.

    ``db_alias`` is the database that owns the connected account named in the
    signed event, or ``None`` for a platform event / an account no configured
    database claims. The caller binds it (``webhook_tenant_scope``) before
    calling :meth:`PaymentRuntimeProvider.record_and_claim_webhook_event` and
    before any provider-specific processing.
    """

    event: Any
    method: Any | None
    workspace: Any | None
    account_id: str | None
    legacy_context: object | None
    provider_slug: str
    api_key: str | None
    db_alias: str | None = None
    #: ``False`` when the event verified but must NOT enter the idempotency
    #: ledger (the Connect/platform cross-delivery guard).
    recordable: bool = True


@dataclass(frozen=True)
class PaymentWebhookIntakeResult:
    """Outcome of recording + claiming the event in the idempotency ledger."""

    payment_event: Any | None
    duplicate: bool
    processable: bool


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
            attach_provider_attempt_reference=AttachProviderAttemptReferenceUseCase(self.payment_orders),
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
            api_key=result.api_key,
            db_alias=getattr(result, "db_alias", None),
            recordable=getattr(result, "recordable", True),
        )

    @staticmethod
    def record_and_claim_webhook_event(
        verification: VerifiedPaymentWebhookResult,
        *,
        claimed_by: str,
        claim_message: str | None = None,
    ) -> PaymentWebhookIntakeResult:
        """Record + claim the verified event in the idempotency ledger.

        THIS IS THE MONEY-PATH WRITE. It used to live inside the verifier,
        which meant it ran before any caller could bind the tenant that owns
        the event — so a dedicated tenant's Connect event landed its ledger row
        in the pooled database. It is a separate step now precisely so the
        caller can bind ``verification.db_alias`` (and open the transaction on
        that alias) around it.
        """
        from components.payments.application.use_cases.record_and_claim_payment_event_use_case import (
            RecordAndClaimPaymentEventUseCase,
        )
        from components.payments.application.use_cases.verify_provider_webhook_use_case import (
            VerifiedProviderWebhookEnvelope,
            VerifyProviderWebhookUseCase,
        )
        from components.payments.infrastructure.repositories.orm_payment_event_claim_repository import (
            OrmPaymentEventClaimRepository,
        )
        from components.payments.infrastructure.repositories.orm_payment_event_recording_repository import (
            OrmPaymentEventRecordingRepository,
        )
        from infrastructure.persistence.workspaces.payments.models import PaymentEvent

        handling = VerifyProviderWebhookUseCase(
            RecordAndClaimPaymentEventUseCase(
                payment_event_recorder=OrmPaymentEventRecordingRepository(),
                payment_event_claims=OrmPaymentEventClaimRepository(),
            )
        ).execute(
            envelope=VerifiedProviderWebhookEnvelope(
                provider=verification.provider_slug,
                event=verification.event,
                account_id=verification.account_id,
                workspace_id=getattr(verification.workspace, "id", None),
                method_id=getattr(verification.method, "id", None),
            ),
            claimed_by=claimed_by,
            claim_message=claim_message,
        )
        payment_event = (
            PaymentEvent.objects.filter(id=handling.intake.payment_event_id).first()
            if handling.intake.payment_event_id
            else None
        )
        return PaymentWebhookIntakeResult(
            payment_event=payment_event,
            duplicate=bool(payment_event and not handling.intake.is_new),
            processable=bool(handling.intake.claimed) if payment_event else True,
        )


def make_payment_runtime_provider() -> PaymentRuntimeProvider:
    return PaymentRuntimeProvider()
