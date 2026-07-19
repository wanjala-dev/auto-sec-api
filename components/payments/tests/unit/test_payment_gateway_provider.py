from __future__ import annotations

from components.payments.application.providers.payment_gateway_provider import (
    PaymentGatewayProvider,
)
from components.payments.domain.errors import UnsupportedPaymentProviderError


class FakeGateway:
    def __init__(self, slug: str):
        self.slug = slug


def test_payment_gateway_provider_normalizes_provider_suffix():
    provider = PaymentGatewayProvider(
        gateways={
            "stripe": FakeGateway("stripe"),
            "bitpay": FakeGateway("bitpay"),
        }
    )

    gateway = provider.get_gateway_for_provider("stripe-us")

    assert gateway.slug == "stripe"


def test_payment_gateway_provider_raises_for_unsupported_provider():
    provider = PaymentGatewayProvider(gateways={"stripe": FakeGateway("stripe")})

    try:
        provider.get_gateway_for_provider("paypal")
    except UnsupportedPaymentProviderError as exc:
        assert str(exc) == "Unsupported payment gateway provider: paypal"
    else:  # pragma: no cover - assertion fallback
        raise AssertionError("Expected UnsupportedPaymentProviderError for unsupported provider")
