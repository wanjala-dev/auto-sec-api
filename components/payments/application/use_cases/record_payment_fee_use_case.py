"""Use case for recording a platform fee against a payment transaction."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import UUID

from components.payments.domain.entities.payment_fee_entity import PaymentFeeEntity
from components.payments.application.ports.payment_balance_transaction_port import (
    PaymentBalanceTransactionPort,
)
from components.payments.application.ports.payment_fee_store_port import PaymentFeeStorePort


@dataclass(frozen=True)
class RecordPaymentFeeCommand:
    transaction_id: UUID
    method_id: UUID
    provider: str
    context: str
    fee_amount: Decimal
    currency: str
    workspace_id: UUID | None = None
    fee_percentage: Decimal = Decimal("0")
    fixed_fee: Decimal = Decimal("0")
    capped_fee: Decimal | None = None
    sales_tax_amount: Decimal = Decimal("0")
    sales_tax_percentage: Decimal = Decimal("0")
    metadata: dict[str, Any] | None = None


@dataclass
class RecordPaymentFeeUseCase:
    """Records a fee and optionally creates a balance transaction."""

    fee_store: PaymentFeeStorePort
    balance_transactions: PaymentBalanceTransactionPort

    def execute(self, command: RecordPaymentFeeCommand) -> PaymentFeeEntity:
        fee, created = self.fee_store.record_fee(
            transaction_id=command.transaction_id,
            method_id=command.method_id,
            provider=command.provider,
            context=command.context,
            fee_amount=command.fee_amount,
            currency=command.currency,
            fee_percentage=command.fee_percentage,
            fixed_fee=command.fixed_fee,
            capped_fee=command.capped_fee,
            sales_tax_amount=command.sales_tax_amount,
            sales_tax_percentage=command.sales_tax_percentage,
            metadata=command.metadata,
        )

        # Only debit the balance ledger when the fee was actually created. On a
        # replay / redelivered success event the unique constraint blocks the
        # duplicate insert (created=False); re-appending here would double-debit
        # the workspace for a single gift's platform fee.
        if created and command.workspace_id:
            self.balance_transactions.append(
                workspace_id=command.workspace_id,
                transaction_type="fee",
                source_type="PaymentFee",
                source_id=fee.id,
                amount=-command.fee_amount,
                fee=command.fee_amount,
                net=-command.fee_amount,
                currency=command.currency,
                provider=command.provider,
                description=f"Platform fee ({command.context})",
            )

        return fee
