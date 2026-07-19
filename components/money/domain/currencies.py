"""Currency primitives for the money context.

The domain is the single source of truth for which ISO 4217 currency
codes the platform supports. The list is deliberately hardcoded —
each code implies product decisions (Stripe Connect region capability,
payout support, display formatting) that we don't want drifting per
environment. Environments that need to restrict further can wrap
these helpers with their own predicate.

All helpers are pure — no Django, no I/O — so they can be called from
any layer.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

# Codes chosen to align with the subset of ISO 4217 currencies Stripe
# Connect supports for payouts today. Adding a new code here is an
# intentional product decision; it should come with a migration plan
# for existing rows and a review of the payment adapter capabilities.
# Reference: https://docs.stripe.com/connect/currencies
SUPPORTED_CURRENCIES: frozenset[str] = frozenset(
    {
        "USD", "EUR", "GBP", "CAD", "AUD", "NZD", "CHF", "JPY", "SGD",
        "HKD", "SEK", "NOK", "DKK", "PLN", "CZK", "HUF", "RON", "BGN",
        "MXN", "BRL", "ARS", "CLP", "COP", "PEN", "UYU",
        "KES", "NGN", "ZAR", "GHS", "EGP", "MAD",
        "INR", "IDR", "MYR", "PHP", "THB", "VND", "KRW",
        "AED", "SAR", "ILS", "TRY",
    }
)

DEFAULT_CURRENCY: str = "USD"

# ISO 4217 minor-unit exponents (number of decimal places). Most
# currencies use 2; the exceptions below are the 0-decimal currencies in
# our supported set. This is the single source of truth for converting a
# major-unit Decimal amount to integer minor units — never assume ×100.
# Adding a 3-decimal currency (BHD/KWD/OMR) means adding it here.
_DEFAULT_MINOR_UNIT_EXPONENT: int = 2
MINOR_UNIT_EXPONENTS: dict[str, int] = {
    "JPY": 0,
    "KRW": 0,
    "CLP": 0,
    "VND": 0,
}


from .errors import UnsupportedCurrencyError  # noqa: E402  (keep errors import after constants)


def supported_currencies() -> frozenset[str]:
    """Return the allowlisted ISO 4217 codes."""
    return SUPPORTED_CURRENCIES


def default_currency() -> str:
    """Return the platform default currency."""
    return DEFAULT_CURRENCY


def normalize(currency: str | None) -> str | None:
    """Return a canonical uppercase 3-letter code, or ``None`` if empty.

    Does not validate allowlist membership — use
    :func:`require_supported` when that matters.
    """
    if currency is None:
        return None
    normalized = str(currency).strip().upper()
    if not normalized:
        return None
    return normalized


def is_supported(currency: str | None) -> bool:
    """Whether the given currency is in the platform allowlist."""
    normalized = normalize(currency)
    return normalized is not None and normalized in SUPPORTED_CURRENCIES


def require_supported(currency: str | None) -> str:
    """Return the normalized currency, raising if it's not allowlisted.

    Raises:
        UnsupportedCurrencyError: the currency is missing or outside
            the allowlist.
    """
    normalized = normalize(currency)
    if normalized is None:
        raise UnsupportedCurrencyError("Currency is required.")
    if normalized not in SUPPORTED_CURRENCIES:
        raise UnsupportedCurrencyError(
            f"Currency {normalized!r} is not in the platform allowlist."
        )
    return normalized


def minor_unit_exponent(currency: str | None) -> int:
    """Return the ISO 4217 minor-unit exponent for ``currency``.

    Defaults to 2 for any currency not explicitly listed (and for an
    unknown/empty currency) — the common case. Pure; does not validate
    allowlist membership.
    """
    normalized = normalize(currency)
    if normalized is None:
        return _DEFAULT_MINOR_UNIT_EXPONENT
    return MINOR_UNIT_EXPONENTS.get(normalized, _DEFAULT_MINOR_UNIT_EXPONENT)


def to_minor_units(amount: Decimal, currency: str | None) -> int:
    """Convert a major-unit ``Decimal`` amount to integer minor units.

    Uses the currency's minor-unit exponent (so JPY 1000 -> 1000, not
    100000). Rounds half-up at the currency's precision. Pure.
    """
    exponent = minor_unit_exponent(currency)
    factor = Decimal(10) ** exponent
    quantized = (Decimal(amount) * factor).quantize(Decimal(1), rounding=ROUND_HALF_UP)
    return int(quantized)
