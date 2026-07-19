"""Use case for recording a payout from webhook data."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from components.payments.domain.entities.payment_payout_entity import PaymentPayoutEntity
from components.payments.application.ports.payment_balance_transaction_port import (
    PaymentBalanceTransactionPort,
)
from components.payments.application.ports.payment_payout_store_port import PaymentPayoutStorePort


@dataclass(frozen=True)
class RecordPayoutCommand:
    workspace_id: UUID
    method_id: UUID
    provider: str
    amount: Decimal
    currency: str
    external_id: str
    arrival_date: datetime | None = None
    metadata: dict[str, Any] | None = None


@dataclass
class RecordPayoutUseCase:
    """Records a payout and creates a balance transaction."""

    payout_store: PaymentPayoutStorePort
    balance_transactions: PaymentBalanceTransactionPort

    def execute(self, command: RecordPayoutCommand) -> PaymentPayoutEntity:
        existing = self.payout_store.find_by_external_id(
            provider=command.provider,
            external_id=command.external_id,
        )
        if existing is not None:
            return existing

        payout = self.payout_store.create_payout(
            workspace_id=command.workspace_id,
            method_id=command.method_id,
            provider=command.provider,
            amount=command.amount,
            currency=command.currency,
            external_id=command.external_id,
            arrival_date=command.arrival_date,
            metadata=command.metadata,
        )

        self.balance_transactions.append(
            workspace_id=command.workspace_id,
            transaction_type="payout",
            source_type="PaymentPayout",
            source_id=payout.id,
            amount=-command.amount,
            fee=Decimal("0"),
            net=-command.amount,
            currency=command.currency,
            provider=command.provider,
            description=f"Payout to bank: {command.external_id}",
        )

        return payout
