"""Unit tests for ISO-4217 minor-unit conversion (API v1 C1 primitive)."""

from decimal import Decimal

import pytest

from components.money.domain import currencies


@pytest.mark.parametrize(
    "currency,expected",
    [
        ("USD", 2), ("KES", 2), ("EUR", 2),
        ("JPY", 0), ("KRW", 0), ("CLP", 0), ("VND", 0),
        ("usd", 2),            # normalized
        ("ZZZ", 2), (None, 2), ("", 2),  # unknown/empty -> default 2
    ],
)
def test_minor_unit_exponent(currency, expected):
    assert currencies.minor_unit_exponent(currency) == expected


@pytest.mark.parametrize(
    "amount,currency,expected",
    [
        (Decimal("50.25"), "USD", 5025),
        (Decimal("0"), "USD", 0),
        (Decimal("1000"), "JPY", 1000),        # 0-decimal: NOT 100000
        (Decimal("50.255"), "USD", 5026),      # round half-up
        (Decimal("19.99"), "KES", 1999),
    ],
)
def test_to_minor_units(amount, currency, expected):
    assert currencies.to_minor_units(amount, currency) == expected
