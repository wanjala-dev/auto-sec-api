"""Currency validators callable from any layer.

These are pure functions, not Django model validators, so they can be
invoked from domain code, serializers, and management commands alike.
Callers catch :class:`CurrencyError` subclasses and translate to HTTP
status codes or CLI output as appropriate.
"""

from __future__ import annotations

from typing import Any

from ..domain.currencies import normalize, require_supported
from ..domain.errors import (
    CurrencyMismatchError,
    UnsupportedCurrencyError,
)


def validate_currency_matches_payment_method(
    currency: str,
    payment_method: Any,
) -> str:
    """Ensure a transaction currency matches the payment method's settlement.

    Returns the normalized (uppercase) currency on success.

    Raises:
        UnsupportedCurrencyError: the currency is missing or outside
            the platform allowlist.
        CurrencyMismatchError: the payment method has a declared
            settlement currency and it disagrees with the transaction.

    The payment method is duck-typed — any object exposing a
    ``settlement_currency`` attribute (or ``currency`` as a fallback)
    works. Passing ``None`` skips the cross-check and only validates
    the currency against the allowlist.
    """
    normalized = require_supported(currency)

    if payment_method is None:
        return normalized

    method_currency = (
        getattr(payment_method, "settlement_currency", None)
        or getattr(payment_method, "currency", None)
    )
    method_currency = normalize(method_currency)
    if method_currency is None:
        # Payment method hasn't been assigned a currency yet (e.g.
        # pre-Stripe-connect or backfill pending). Nothing to check.
        return normalized

    if normalized != method_currency:
        raise CurrencyMismatchError(
            f"Currency {normalized} does not match the payment method's "
            f"settlement currency {method_currency}."
        )

    return normalized


__all__ = [
    "CurrencyMismatchError",
    "UnsupportedCurrencyError",
    "validate_currency_matches_payment_method",
]
