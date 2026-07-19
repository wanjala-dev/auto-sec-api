"""No-op adapter for environments without Stripe credentials."""

from __future__ import annotations

from ...application.ports.stripe_account_currency_port import (
    StripeAccountCurrencyPort,
)


class NullStripeAccountCurrencyAdapter(StripeAccountCurrencyPort):
    def resolve_default_currency(self, provider_account_id: str) -> str | None:
        return None
