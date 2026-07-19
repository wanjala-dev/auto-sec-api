from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any
from uuid import UUID


@dataclass(frozen=True)
class PaymentFeeEntity:
    id: UUID
    transaction_id: UUID
    method_id: UUID
    provider: str
    context: str
    fee_amount: Decimal
    currency: str
    fee_percentage: Decimal = Decimal("0")
    fixed_fee: Decimal = Decimal("0")
    capped_fee: Decimal | None = None
    sales_tax_amount: Decimal = Decimal("0")
    sales_tax_percentage: Decimal = Decimal("0")
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.fee_amount < 0:
            raise ValueError("PaymentFeeEntity.fee_amount must be non-negative.")
