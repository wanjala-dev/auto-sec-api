"""Reusable v1 money representation (C1 of the API v1 contract).

Every v1 endpoint that returns an amount uses ``build_money_v1`` so the
money shape is identical across all 27 contexts — never reinvented per
serializer. See `docs/plans/API_V1_CONTRACT_DESIGN.md` C1.

The v1 money object is::

    {"amount_minor": 5025, "currency": "USD", "amount_display": "USD 50.25"}

* ``amount_minor`` — integer minor units, computed with the currency's
  ISO 4217 exponent (so JPY 1000 -> 1000, never 100000).
* ``currency`` — normalized uppercase ISO code (``None`` only if truly absent).
* ``amount_display`` — server-formatted string at the currency's precision,
  so clients never guess decimal places or rounding.

Pure (no DRF, no Django, no I/O) so it's callable from any serializer /
mapper and trivially unit-testable.
"""

from __future__ import annotations

from decimal import Decimal

from components.money.domain import currencies


def build_money_v1(amount, currency: str | None) -> dict | None:
    """Build the canonical v1 money object from a major-unit amount + currency.

    Returns ``None`` when ``amount`` is ``None`` (C8: the caller decides
    whether the field is present-null). ``amount`` may be a ``Decimal``,
    ``int``, ``float`` (coerced via ``Decimal(str(...))``), or numeric string.
    """
    if amount is None:
        return None

    decimal_amount = amount if isinstance(amount, Decimal) else Decimal(str(amount))
    normalized_currency = currencies.normalize(currency) or currencies.default_currency()
    exponent = currencies.minor_unit_exponent(normalized_currency)

    return {
        "amount_minor": currencies.to_minor_units(decimal_amount, normalized_currency),
        "currency": normalized_currency,
        "amount_display": _format_display(decimal_amount, normalized_currency, exponent),
    }


def build_money_v1_from_minor(amount_minor, currency: str | None) -> dict | None:
    """Build the canonical v1 money object from an ALREADY-minor-unit amount.

    Use this — never ``build_money_v1`` — when the source value is already in
    integer minor units (e.g. a Stripe ``amount_due`` / ``unit_amount``, which
    Stripe always expresses in the smallest currency unit). Passing a minor
    value to ``build_money_v1`` would multiply by the exponent a second time
    (``2999`` cents -> ``299900`` minor), inflating the figure 100×.

    The major-unit ``Decimal`` used for ``amount_display`` is derived back from
    the minor value with the currency's ISO-4217 exponent, so the object is
    internally consistent (``amount_minor`` and ``amount_display`` describe the
    same money). Returns ``None`` when ``amount_minor`` is ``None`` (C8).

    ``amount_minor`` may be an ``int`` or a numeric string; it is rounded to the
    nearest integer minor unit.
    """
    if amount_minor is None:
        return None

    minor_decimal = (
        amount_minor if isinstance(amount_minor, Decimal) else Decimal(str(amount_minor))
    )
    minor_int = int(minor_decimal.to_integral_value(rounding="ROUND_HALF_UP"))
    normalized_currency = currencies.normalize(currency) or currencies.default_currency()
    exponent = currencies.minor_unit_exponent(normalized_currency)
    major_amount = Decimal(minor_int) / (Decimal(10) ** exponent)

    return {
        "amount_minor": minor_int,
        "currency": normalized_currency,
        "amount_display": _format_display(major_amount, normalized_currency, exponent),
    }


def _format_display(amount: Decimal, currency: str, exponent: int) -> str:
    """``"USD 50.25"`` / ``"JPY 1,000"`` — code + amount at currency precision."""
    return f"{currency} {amount:,.{exponent}f}"
