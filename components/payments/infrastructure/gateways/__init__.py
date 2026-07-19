from __future__ import annotations

from importlib import import_module

__all__ = [
    "PaymentGatewayProvider",
    "PaymentPlanSyncGateway",
    "StripeConnectOnboardingGateway",
    "make_payment_gateway_provider",
]


def __getattr__(name: str):
    if name in {"PaymentGatewayProvider", "make_payment_gateway_provider"}:
        module = import_module(
            "components.payments.application.providers.payment_gateway_provider"
        )
        return getattr(module, name)
    if name == "StripeConnectOnboardingGateway":
        return import_module(
            "components.payments.infrastructure.gateways.stripe_connect_onboarding_gateway"
        ).StripeConnectOnboardingGateway
    if name == "PaymentPlanSyncGateway":
        return import_module(
            "components.payments.infrastructure.gateways.payment_plan_sync_gateway"
        ).PaymentPlanSyncGateway
    raise AttributeError(name)
