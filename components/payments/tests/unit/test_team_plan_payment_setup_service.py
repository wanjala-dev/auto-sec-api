from __future__ import annotations

from components.payments.application.service import (
    TeamPlanPaymentSetupService,
)


class FakeSetupStore:
    def __init__(self):
        self.calls = []

    def ensure_subscription_payment_method(self, *, workspace):
        self.calls.append(("method", workspace))
        return "method-result"

    def ensure_platform_customer(self, *, workspace, method, email=None, name=None):
        self.calls.append(("customer", workspace, method, email, name))
        return "cus_123"

    def ensure_team_plan_payment_plan(self, *, workspace, plan, method, currency_override=None):
        self.calls.append(("plan", workspace, plan, method, currency_override))
        return "plan-result"


def test_team_plan_payment_setup_service_delegates_to_store():
    store = FakeSetupStore()
    service = TeamPlanPaymentSetupService(store)

    assert service.ensure_subscription_payment_method("workspace") == "method-result"
    assert (
        service.ensure_platform_customer(
            "workspace",
            method="method",
            email="owner@example.com",
            name="Owner",
        )
        == "cus_123"
    )
    assert (
        service.ensure_team_plan_payment_plan(
            "workspace",
            plan="plan",
            method="method",
            currency_override="usd",
        )
        == "plan-result"
    )
    assert store.calls == [
        ("method", "workspace"),
        ("customer", "workspace", "method", "owner@example.com", "Owner"),
        ("plan", "workspace", "plan", "method", "usd"),
    ]
