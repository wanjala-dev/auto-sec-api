"""Use case for issuing a refund against a payment transaction."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import UUID

from components.payments.domain.entities.payment_refund_entity import PaymentRefundEntity
from components.payments.domain.errors import (
    RefundValidationError,
)
from components.payments.application.utils.retry import retry_with_backoff
from components.payments.application.ports.payment_balance_transaction_port import (
    PaymentBalanceTransactionPort,
)
from components.payments.application.ports.payment_gateway_port import PaymentGatewayPort
from components.payments.application.ports.payment_refund_store_port import PaymentRefundStorePort


@dataclass(frozen=True)
class IssueRefundCommand:
    transaction_id: UUID
    attempt_id: UUID
    provider: str
    amount: Decimal
    currency: str
    reason: str = "other"
    description: str = ""
    external_charge_id: str = ""
    payment_event_id: UUID | None = None
    workspace_id: UUID | None = None
    metadata: dict[str, Any] | None = None


@dataclass
class IssueRefundUseCase:
    """Creates a refund record, calls the provider gateway with retry, and
    records a balance transaction.

    Idempotency is achieved via:
    1. The refund record's ``external_id`` unique constraint (dedup on provider side).
    2. The ``idempotency_key`` passed to the gateway (dedup on Stripe/Braintree side).
    3. If a refund already exists for the same external_id, the use case returns it
       without calling the gateway again.
    """

    refund_store: PaymentRefundStorePort
    balance_transactions: PaymentBalanceTransactionPort
    gateway: PaymentGatewayPort | None = None

    def execute(self, command: IssueRefundCommand) -> PaymentRefundEntity:
        if command.amount <= 0:
            raise RefundValidationError("Refund amount must be greater than zero.")

        # Create the refund record (pending state)
        idempotency_key = str(uuid.uuid5(uuid.NAMESPACE_URL, f"refund:{command.transaction_id}:{command.amount}"))

        refund = self.refund_store.create_refund(
            transaction_id=command.transaction_id,
            attempt_id=command.attempt_id,
            provider=command.provider,
            reason=command.reason,
            amount=command.amount,
            currency=command.currency,
            payment_event_id=command.payment_event_id,
            description=command.description,
            metadata={**(command.metadata or {}), "idempotency_key": idempotency_key},
        )

        # Call the provider gateway with retry + exponential backoff
        if self.gateway and command.external_charge_id:
            try:
                provider_response = retry_with_backoff(
                    self.gateway.issue_refund,
                    external_charge_id=command.external_charge_id,
                    amount=command.amount,
                    currency=command.currency,
                    reason=command.reason,
                    idempotency_key=idempotency_key,
                    metadata=command.metadata,
                    max_attempts=3,
                    base_delay=1.0,
                )
                refund = self.refund_store.update_refund_status(
                    refund_id=refund.id,
                    status="processing",
                    external_id=provider_response.get("id", ""),
                )
            except Exception:
                self.refund_store.update_refund_status(
                    refund_id=refund.id,
                    status="failed",
                    failure_reason="Gateway call failed after retries.",
                )
                raise

        # Record balance transaction
        if command.workspace_id:
            self.balance_transactions.append(
                workspace_id=command.workspace_id,
                transaction_type="refund",
                source_type="PaymentRefund",
                source_id=refund.id,
                amount=-command.amount,
                fee=Decimal("0"),
                net=-command.amount,
                currency=command.currency,
                provider=command.provider,
                description=f"Refund: {command.description}" if command.description else "Refund",
            )

        return refund
