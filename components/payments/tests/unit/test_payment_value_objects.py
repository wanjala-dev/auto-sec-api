from __future__ import annotations

from decimal import Decimal

import pytest

from components.payments.domain.value_objects import (
    ExternalReference,
    Money,
    PaymentEventType,
    ProviderEventId,
)


def test_money_normalizes_currency():
    money = Money(amount=Decimal("5.00"), currency="USD")

    assert money.currency == "usd"


def test_external_reference_requires_value():
    with pytest.raises(ValueError, match="ExternalReference.value is required"):
        ExternalReference("  ")


def test_provider_event_id_requires_value():
    with pytest.raises(ValueError, match="ProviderEventId.value is required"):
        ProviderEventId("")


def test_payment_event_type_requires_value():
    with pytest.raises(ValueError, match="PaymentEventType.value is required"):
        PaymentEventType(" ")
