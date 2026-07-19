"""Port for persisting a backfilled settlement currency on a payment method.

Used by the settlement-currency resolver after a live Stripe lookup so
the next checkout doesn't need to round-trip to Stripe again. Kept as a
single-purpose port rather than reusing the broader payment-method
management port — the resolver only needs to write one field.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import UUID


class PaymentMethodSettlementCurrencyWriterPort(ABC):
    @abstractmethod
    def persist_settlement_currency(
        self, *, method_id: UUID, settlement_currency: str
    ) -> None:
        """Persist ``settlement_currency`` on the payment method row.

        Implementations should be idempotent — calling twice with the
        same value is a no-op. Should not raise on a missing row;
        callers treat persistence failures as best-effort.
        """
