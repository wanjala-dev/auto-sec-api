"""Port for resolving a Stripe connected account's settlement currency.

Controllers and services must call this port rather than reaching
directly into the Stripe SDK, so tests can substitute a fake and
non-Stripe environments can run against a no-op adapter.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class StripeAccountCurrencyPort(ABC):
    """Contract for looking up a Stripe connected account's default currency."""

    @abstractmethod
    def resolve_default_currency(self, provider_account_id: str) -> str | None:
        """Return the ISO 4217 uppercase currency for a connected account.

        Should return ``None`` (not raise) when the account cannot be
        reached — callers decide whether a missing currency is fatal.
        Implementations are free to raise on programming errors (e.g.
        blank ``provider_account_id``).
        """
