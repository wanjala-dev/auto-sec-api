"""Unit tests for validate_currency_matches_payment_method."""

from __future__ import annotations

import pytest

from components.money.application.currency_validator_service import (
    validate_currency_matches_payment_method,
)
from components.money.domain.errors import (
    CurrencyMismatchError,
    UnsupportedCurrencyError,
)


class _FakeMethod:
    def __init__(self, *, settlement_currency=None, currency=None):
        self.settlement_currency = settlement_currency
        self.currency = currency


class TestValidateCurrencyMatchesPaymentMethod:
    def test_matches_settlement_currency_success(self):
        result = validate_currency_matches_payment_method(
            "usd", _FakeMethod(settlement_currency="USD")
        )
        assert result == "USD"

    def test_currency_normalized_in_return(self):
        result = validate_currency_matches_payment_method(
            "eur", _FakeMethod(settlement_currency="eur")
        )
        assert result == "EUR"

    def test_raises_on_mismatch(self):
        with pytest.raises(CurrencyMismatchError) as exc_info:
            validate_currency_matches_payment_method(
                "EUR", _FakeMethod(settlement_currency="USD")
            )
        msg = str(exc_info.value)
        assert "EUR" in msg
        assert "USD" in msg

    def test_raises_on_unsupported_currency_even_if_method_missing(self):
        with pytest.raises(UnsupportedCurrencyError):
            validate_currency_matches_payment_method("XYZ", None)

    def test_raises_on_empty_currency(self):
        with pytest.raises(UnsupportedCurrencyError):
            validate_currency_matches_payment_method("", _FakeMethod())

    def test_payment_method_none_skips_cross_check(self):
        # Valid currency, no payment method → should return the
        # normalized currency without raising.
        assert validate_currency_matches_payment_method("USD", None) == "USD"

    def test_payment_method_with_blank_currency_skips_cross_check(self):
        # Pre-backfill rows exist with settlement_currency=None. The
        # validator should pass those through rather than blocking
        # writes while backfill is pending.
        assert (
            validate_currency_matches_payment_method(
                "USD", _FakeMethod(settlement_currency=None)
            )
            == "USD"
        )

    def test_falls_back_to_generic_currency_attribute(self):
        # Some legacy payment method shapes used ``currency`` instead
        # of ``settlement_currency``. The validator should still honor
        # them so the check is uniform.
        assert (
            validate_currency_matches_payment_method(
                "USD", _FakeMethod(currency="USD")
            )
            == "USD"
        )

    def test_raises_on_legacy_currency_mismatch(self):
        with pytest.raises(CurrencyMismatchError):
            validate_currency_matches_payment_method(
                "EUR", _FakeMethod(currency="USD")
            )
