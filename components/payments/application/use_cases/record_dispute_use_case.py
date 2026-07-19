"""Use case for recording a payment dispute from webhook data."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from components.payments.domain.entities.payment_dispute_entity import PaymentDisputeEntity
from components.payments.application.ports.payment_balance_transaction_port import (
    PaymentBalanceTransactionPort,
)
from components.payments.application.ports.payment_dispute_store_port import PaymentDisputeStorePort


@dataclass(frozen=True)
class RecordDisputeCommand:
    transaction_id: UUID
    provider: str
    status: str
    category: str
    amount: Decimal
    currency: str
    external_id: str
    workspace_id: UUID | None = None
    payment_event_id: UUID | None = None
    evidence_due_by: datetime | None = None
    disputed_at: datetime | None = None
    metadata: dict[str, Any] | None = None


@dataclass
class RecordDisputeUseCase:
    """Records a dispute and creates a balance transaction for the hold."""

    dispute_store: PaymentDisputeStorePort
    balance_transactions: PaymentBalanceTransactionPort

    def execute(self, command: RecordDisputeCommand) -> PaymentDisputeEntity:
        existing = self.dispute_store.find_by_external_id(
            provider=command.provider,
            external_id=command.external_id,
        )
        if existing is not None:
            return existing

        dispute = self.dispute_store.create_dispute(
            transaction_id=command.transaction_id,
            provider=command.provider,
            status=command.status,
            category=command.category,
            amount=command.amount,
            currency=command.currency,
            external_id=command.external_id,
            payment_event_id=command.payment_event_id,
            evidence_due_by=command.evidence_due_by,
            disputed_at=command.disputed_at,
            metadata=command.metadata,
        )

        if command.workspace_id:
            self.balance_transactions.append(
                workspace_id=command.workspace_id,
                transaction_type="dispute",
                source_type="PaymentDispute",
                source_id=dispute.id,
                amount=-command.amount,
                fee=Decimal("0"),
                net=-command.amount,
                currency=command.currency,
                provider=command.provider,
                description=f"Dispute ({command.category}): {command.external_id}",
            )

        return dispute
