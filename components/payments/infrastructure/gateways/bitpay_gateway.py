from __future__ import annotations

from components.payments.infrastructure.adapters import BitpayPaymentAdapter


class BitpayGatewayAdapter:
    slug = "bitpay"

    def __init__(self, adapter: BitpayPaymentAdapter | None = None):
        self.adapter = adapter or BitpayPaymentAdapter()

    def verify_webhook(self, request, endpoint_name, candidate_methods):
        return self.adapter.verify_webhook(request, endpoint_name, candidate_methods)

    def create_checkout_session(self, method, plan, **kwargs):
        return self.adapter.create_checkout_session(method, plan, **kwargs)

    def ensure_plan_resources(self, method, plan) -> None:
        self.adapter.ensure_plan_resources(method, plan)
