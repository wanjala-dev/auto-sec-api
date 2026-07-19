"""Provider that returns the active StripeAccountCurrencyPort.

Follows the same pattern as PaymentGatewayProvider: the default
implementation uses the real Stripe adapter; tests and non-Stripe
environments inject the ``NullStripeAccountCurrencyAdapter`` directly
when constructing the provider.

No framework or SDK imports at module scope — keeps the application
layer free of ``django``, ``stripe``, and similar per the architecture
rules.
"""

from __future__ import annotations

from typing import Callable

from ..ports.stripe_account_currency_port import StripeAccountCurrencyPort


class StripeAccountCurrencyProvider:
    def __init__(
        self,
        adapter_factory: Callable[[], StripeAccountCurrencyPort] | None = None,
    ) -> None:
        self._adapter_factory = adapter_factory or self._default_adapter

    @staticmethod
    def _default_adapter() -> StripeAccountCurrencyPort:
        from ...infrastructure.adapters.stripe_account_currency_adapter import (
            StripeAccountCurrencyAdapter,
        )

        return StripeAccountCurrencyAdapter()

    def build(self) -> StripeAccountCurrencyPort:
        return self._adapter_factory()
