from __future__ import annotations

from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID

from components.payments.domain.entities.payment_fee_entity import PaymentFeeEntity


class PaymentFeeStorePort(Protocol):
    def record_fee(
        self,
        *,
        transaction_id: UUID,
        method_id: UUID,
        provider: str,
        context: str,
        fee_amount: Decimal,
        currency: str,
        fee_percentage: Decimal = Decimal("0"),
        fixed_fee: Decimal = Decimal("0"),
        capped_fee: Decimal | None = None,
        sales_tax_amount: Decimal = Decimal("0"),
        sales_tax_percentage: Decimal = Decimal("0"),
        metadata: dict[str, Any] | None = None,
    ) -> tuple[PaymentFeeEntity, bool]:
        """Record a fee, returning ``(fee, created)``.

        ``created`` is ``False`` when a fee already existed for this
        ``(transaction, context)`` — the unique constraint blocked the insert
        and the existing row is returned. Callers MUST NOT re-run downstream
        side effects (e.g. appending a balance-ledger debit) when ``created``
        is ``False``, or a replayed success event double-debits the workspace.
        """
        ...
