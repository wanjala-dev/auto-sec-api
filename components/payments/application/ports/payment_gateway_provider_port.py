from __future__ import annotations

from typing import Protocol

from components.payments.application.ports.payment_gateway_port import PaymentGatewayPort


class PaymentGatewayProviderPort(Protocol):
    def get_gateway_for_provider(self, provider_slug: str) -> PaymentGatewayPort: ...

    def registered_gateways(self) -> list[tuple[str, PaymentGatewayPort]]: ...
