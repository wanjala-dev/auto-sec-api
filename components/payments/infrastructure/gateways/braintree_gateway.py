from __future__ import annotations

from components.payments.infrastructure.adapters import BraintreePaymentAdapter


class BraintreeGatewayAdapter:
    slug = "braintree"

    def __init__(self, adapter: BraintreePaymentAdapter | None = None):
        if adapter is not None:
            self.adapter = adapter
            return
        if BraintreePaymentAdapter is None:
            raise ImportError("Braintree adapter is unavailable in this environment.")
        self.adapter = BraintreePaymentAdapter()

    def verify_webhook(self, request, endpoint_name, candidate_methods):
        return self.adapter.verify_webhook(request, endpoint_name, candidate_methods)

    def create_checkout_session(self, method, plan, **kwargs):
        return self.adapter.create_checkout_session(method, plan, **kwargs)

    def capture_payment(self, method, identifier, **kwargs):
        return self.adapter.capture_payment(method, identifier, **kwargs)

    def ensure_plan_resources(self, method, plan) -> None:
        self.adapter.ensure_plan_resources(method, plan)
