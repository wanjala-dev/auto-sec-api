"""Provider for the payment-method settlement currency writer adapter.

Cross-context callers (sponsorship) consume this provider instead of
importing
``components.money.infrastructure.adapters.django_payment_method_settlement_currency_writer_adapter``
directly.
"""

from __future__ import annotations

from typing import Any


class PaymentMethodSettlementCurrencyWriterProvider:
    def adapter(self) -> Any:
        from components.money.infrastructure.adapters.django_payment_method_settlement_currency_writer_adapter import (
            DjangoPaymentMethodSettlementCurrencyWriterAdapter,
        )

        return DjangoPaymentMethodSettlementCurrencyWriterAdapter()


_default = PaymentMethodSettlementCurrencyWriterProvider()


def get_payment_method_settlement_currency_writer_provider() -> PaymentMethodSettlementCurrencyWriterProvider:
    return _default
