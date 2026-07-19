"""Provider for Stripe invoice helper utilities.

Cross-context callers (sponsorship use cases) consume this provider
instead of importing
``components.payments.infrastructure.services.stripe_invoice_helpers``
directly. Keeps the application layer's import graph framework-free
and respects the cross-context-infrastructure-boundary rule.
"""

from __future__ import annotations

from typing import Any


class StripeInvoiceHelpersProvider:
    """Façade over the payments-context Stripe-invoice helpers."""

    def __getattr__(self, name: str) -> Any:
        """Lazy-delegate any helper name to the underlying module."""
        from components.payments.infrastructure.services import (
            stripe_invoice_helpers,
        )
        if not hasattr(stripe_invoice_helpers, name):
            raise AttributeError(
                f"stripe_invoice_helpers has no attribute {name!r}"
            )
        return getattr(stripe_invoice_helpers, name)


_default = StripeInvoiceHelpersProvider()


def get_stripe_invoice_helpers_provider() -> StripeInvoiceHelpersProvider:
    return _default
