"""Use case for closing a dispute (won/lost/accepted)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from components.payments.domain.entities.payment_dispute_entity import PaymentDisputeEntity
from components.payments.application.ports.payment_balance_transaction_port import (
    PaymentBalanceTransactionPort,
)
from components.payments.application.ports.payment_dispute_store_port import PaymentDisputeStorePort


@dataclass(frozen=True)
class CloseDisputeCommand:
    dispute_id: UUID
    status: str  # won, lost, or accepted
    workspace_id: UUID | None = None
    resolved_at: datetime | None = None


@dataclass
class CloseDisputeUseCase:
    """Updates dispute status and creates a reversal balance transaction if won."""

    dispute_store: PaymentDisputeStorePort
    balance_transactions: PaymentBalanceTransactionPort

    def execute(self, command: CloseDisputeCommand) -> PaymentDisputeEntity:
        dispute = self.dispute_store.update_dispute_status(
            dispute_id=command.dispute_id,
            status=command.status,
            resolved_at=command.resolved_at,
        )

        if command.status == "won" and command.workspace_id:
            self.balance_transactions.append(
                workspace_id=command.workspace_id,
                transaction_type="dispute_reversal",
                source_type="PaymentDispute",
                source_id=dispute.id,
                amount=dispute.amount,
                fee=Decimal("0"),
                net=dispute.amount,
                currency=dispute.currency,
                provider=dispute.provider,
                description=f"Dispute won — funds reinstated: {dispute.external_id}",
            )

        return dispute
