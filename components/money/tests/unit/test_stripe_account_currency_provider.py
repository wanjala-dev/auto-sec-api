"""Unit tests for the StripeAccountCurrencyProvider.

The provider is a thin wiring layer: it should (a) return the real
adapter by default, and (b) honor an injected factory so tests and
non-Stripe environments can substitute a null adapter.
"""

from __future__ import annotations

from components.money.application.ports.stripe_account_currency_port import (
    StripeAccountCurrencyPort,
)
from components.money.application.providers.stripe_account_currency_provider import (
    StripeAccountCurrencyProvider,
)
from components.money.infrastructure.adapters.null_stripe_account_currency_adapter import (
    NullStripeAccountCurrencyAdapter,
)
from components.money.infrastructure.adapters.stripe_account_currency_adapter import (
    StripeAccountCurrencyAdapter,
)


class TestStripeAccountCurrencyProvider:
    def test_default_returns_stripe_adapter(self):
        provider = StripeAccountCurrencyProvider()
        port = provider.build()
        assert isinstance(port, StripeAccountCurrencyAdapter)
        assert isinstance(port, StripeAccountCurrencyPort)

    def test_injected_factory_is_honored(self):
        provider = StripeAccountCurrencyProvider(
            adapter_factory=NullStripeAccountCurrencyAdapter
        )
        port = provider.build()
        assert isinstance(port, NullStripeAccountCurrencyAdapter)

    def test_build_invokes_factory_each_time(self):
        calls = []

        def _factory() -> StripeAccountCurrencyPort:
            calls.append(1)
            return NullStripeAccountCurrencyAdapter()

        provider = StripeAccountCurrencyProvider(adapter_factory=_factory)
        provider.build()
        provider.build()
        assert len(calls) == 2


class TestNullStripeAccountCurrencyAdapter:
    def test_always_returns_none(self):
        adapter = NullStripeAccountCurrencyAdapter()
        assert adapter.resolve_default_currency("acct_anything") is None
        assert adapter.resolve_default_currency("") is None
