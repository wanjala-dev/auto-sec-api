"""Unit tests for the reusable v1 money builder (API v1 C1)."""

from decimal import Decimal

from components.money.mappers.rest.money_serializers import build_money_v1


def test_two_decimal_currency():
    assert build_money_v1(Decimal("50.25"), "USD") == {
        "amount_minor": 5025,
        "currency": "USD",
        "amount_display": "USD 50.25",
    }


def test_zero_decimal_currency_does_not_overscale():
    assert build_money_v1(Decimal("1000"), "JPY") == {
        "amount_minor": 1000,
        "currency": "JPY",
        "amount_display": "JPY 1,000",
    }


def test_currency_is_normalized():
    assert build_money_v1(Decimal("5"), "usd")["currency"] == "USD"


def test_missing_currency_defaults_to_platform_default():
    out = build_money_v1(Decimal("5"), None)
    assert out["currency"] == "USD"
    assert out["amount_minor"] == 500


def test_none_amount_is_none():
    assert build_money_v1(None, "USD") is None


def test_accepts_string_amount():
    assert build_money_v1("50.25", "USD")["amount_minor"] == 5025
