"""Unit tests for components/money/domain/currencies.py."""

from __future__ import annotations

import pytest

from components.money.domain.currencies import (
    DEFAULT_CURRENCY,
    SUPPORTED_CURRENCIES,
    default_currency,
    is_supported,
    normalize,
    require_supported,
    supported_currencies,
)
from components.money.domain.errors import UnsupportedCurrencyError


class TestSupportedCurrencies:
    def test_includes_major_fiat(self):
        for code in ("USD", "EUR", "GBP", "CAD", "JPY"):
            assert code in SUPPORTED_CURRENCIES

    def test_covers_platform_target_markets(self):
        # Emerging markets we've committed to supporting.
        for code in ("KES", "NGN", "ZAR", "INR", "BRL", "IDR", "THB"):
            assert code in SUPPORTED_CURRENCIES

    def test_all_codes_are_uppercase_iso_4217_shape(self):
        for code in SUPPORTED_CURRENCIES:
            assert len(code) == 3
            assert code.isupper()
            assert code.isalpha()

    def test_returns_frozenset_from_helper(self):
        result = supported_currencies()
        assert isinstance(result, frozenset)
        assert result == SUPPORTED_CURRENCIES

    def test_default_is_usd(self):
        assert default_currency() == "USD"
        assert DEFAULT_CURRENCY == "USD"

    def test_default_is_supported(self):
        assert DEFAULT_CURRENCY in SUPPORTED_CURRENCIES


class TestNormalize:
    @pytest.mark.parametrize(
        "given,expected",
        [
            ("usd", "USD"),
            ("USD", "USD"),
            ("  eur  ", "EUR"),
            ("Gbp", "GBP"),
        ],
    )
    def test_uppercases_and_trims(self, given, expected):
        assert normalize(given) == expected

    @pytest.mark.parametrize("given", [None, "", "   ", "\t\n"])
    def test_empty_and_none_collapse_to_none(self, given):
        assert normalize(given) is None

    def test_does_not_enforce_allowlist(self):
        # Normalize is deliberately lax; allowlist membership is
        # enforced separately by require_supported.
        assert normalize("xyz") == "XYZ"


class TestIsSupported:
    def test_true_for_allowlisted(self):
        assert is_supported("USD") is True
        assert is_supported("eur") is True  # normalization runs first

    def test_false_for_unknown(self):
        assert is_supported("XYZ") is False

    def test_false_for_empty(self):
        assert is_supported(None) is False
        assert is_supported("") is False


class TestRequireSupported:
    def test_returns_normalized_on_success(self):
        assert require_supported("usd") == "USD"

    def test_raises_on_missing(self):
        with pytest.raises(UnsupportedCurrencyError):
            require_supported(None)

    def test_raises_on_empty(self):
        with pytest.raises(UnsupportedCurrencyError):
            require_supported("")

    def test_raises_on_unknown_code(self):
        with pytest.raises(UnsupportedCurrencyError) as exc_info:
            require_supported("XYZ")
        # Message should mention the offending code so logs point
        # operators at the bad input, not at a generic failure.
        assert "XYZ" in str(exc_info.value)
