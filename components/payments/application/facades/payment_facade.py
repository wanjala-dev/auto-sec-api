"""Published API for the payments bounded context.

Other contexts (sponsorship, commerce, budgeting, etc.) should import
from this facade when they need payment-related operations.  This is the
payments context's **published language** — the only module external
contexts should touch.

Anything NOT re-exported here is an internal implementation detail.
"""
from __future__ import annotations

# ── Provider factories (composition root) ────────────────────────────
from components.payments.application.providers import (  # noqa: F401
    PaymentGatewayProvider,
    PaymentRuntimeProvider,
    VerifiedPaymentWebhookResult,
    make_payment_gateway_provider,
    make_payment_runtime_provider,
)

# ── Application services ─────────────────────────────────────────────
from components.payments.application.service import (  # noqa: F401
    PaymentCaptureRecordingResult,
    PaymentCaptureRecordingService,
    PaymentServicesFactory,
)

# ── Use cases ─────────────────────────────────────────────────────────
from components.payments.application.use_cases.record_successful_payment_use_case import (  # noqa: F401
    RecordSuccessfulPaymentUseCase,
)

# ── Infrastructure utilities re-exported as published API ─────────────
# These are pure functions with no side effects, safe to expose.


def stripe_amount_to_decimal(amount, currency=None):
    """Convert a Stripe integer amount to a Decimal."""
    from components.payments.infrastructure.adapters.payment_utils import (
        stripe_amount_to_decimal as _convert,
    )

    return _convert(amount, currency)


def resolve_db_alias_for_stripe_account(account_id):
    """Return the DB alias for a given Stripe connected account ID."""
    from components.payments.infrastructure.adapters.payment_utils import (
        resolve_db_alias_for_stripe_account as _resolve,
    )

    return _resolve(account_id)


# ── Payment event state (idempotency tracking) ───────────────────────


def get_payment_event_state_adapter():
    """Return the payment event state adapter for idempotent event processing."""
    from components.payments.infrastructure.adapters.payment_event_state import (
        PaymentEventStateAdapter,
    )

    return PaymentEventStateAdapter()


# ── Provider wiring helpers ───────────────────────────────────────────


def get_payment_flow_state_provider():
    """Return a PaymentFlowStateProvider instance."""
    from components.payments.application.providers.payment_flow_state_provider import (
        PaymentFlowStateProvider,
    )

    return PaymentFlowStateProvider()


def get_payment_infrastructure_factory():
    """Return a PaymentInfrastructureFactory instance."""
    from components.payments.application.providers.payment_infrastructure_factory import (
        PaymentInfrastructureFactory,
    )

    return PaymentInfrastructureFactory()


# ── Use cases (published for cross-context consumption) ──────────────


def build_issue_refund_use_case():
    """Build an IssueRefundUseCase with default wiring."""
    from components.payments.application.use_cases.issue_refund_use_case import (
        IssueRefundUseCase,
    )
    from components.payments.infrastructure.repositories.orm_payment_balance_transaction_repository import (
        OrmPaymentBalanceTransactionRepository,
    )
    from components.payments.infrastructure.repositories.orm_payment_refund_repository import (
        OrmPaymentRefundRepository,
    )

    return IssueRefundUseCase(
        refund_store=OrmPaymentRefundRepository(),
        balance_transactions=OrmPaymentBalanceTransactionRepository(),
    )


def build_record_dispute_use_case():
    """Build a RecordDisputeUseCase with default wiring."""
    from components.payments.application.use_cases.record_dispute_use_case import (
        RecordDisputeUseCase,
    )
    from components.payments.infrastructure.repositories.orm_payment_balance_transaction_repository import (
        OrmPaymentBalanceTransactionRepository,
    )
    from components.payments.infrastructure.repositories.orm_payment_dispute_repository import (
        OrmPaymentDisputeRepository,
    )

    return RecordDisputeUseCase(
        dispute_store=OrmPaymentDisputeRepository(),
        balance_transactions=OrmPaymentBalanceTransactionRepository(),
    )


def build_record_payment_fee_use_case():
    """Build a RecordPaymentFeeUseCase with default wiring."""
    from components.payments.application.use_cases.record_payment_fee_use_case import (
        RecordPaymentFeeUseCase,
    )
    from components.payments.infrastructure.repositories.orm_payment_balance_transaction_repository import (
        OrmPaymentBalanceTransactionRepository,
    )
    from components.payments.infrastructure.repositories.orm_payment_fee_repository import (
        OrmPaymentFeeRepository,
    )

    return RecordPaymentFeeUseCase(
        fee_store=OrmPaymentFeeRepository(),
        balance_transactions=OrmPaymentBalanceTransactionRepository(),
    )


def build_record_payout_use_case():
    """Build a RecordPayoutUseCase with default wiring."""
    from components.payments.application.use_cases.record_payout_use_case import (
        RecordPayoutUseCase,
    )
    from components.payments.infrastructure.repositories.orm_payment_balance_transaction_repository import (
        OrmPaymentBalanceTransactionRepository,
    )
    from components.payments.infrastructure.repositories.orm_payment_payout_repository import (
        OrmPaymentPayoutRepository,
    )

    return RecordPayoutUseCase(
        payout_store=OrmPaymentPayoutRepository(),
        balance_transactions=OrmPaymentBalanceTransactionRepository(),
    )
