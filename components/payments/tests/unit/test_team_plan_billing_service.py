from __future__ import annotations

from components.payments.application.service import (
    TeamPlanBillingService,
)


class FakeTeamPlanBillingStore:
    def __init__(self):
        self.calls = []

    def checkout_team_plan(self, **kwargs):
        self.calls.append(("checkout", kwargs))
        return {"status": "updated"}, 200

    def preview_plan_change(self, **kwargs):
        self.calls.append(("preview", kwargs))
        return {"amount_due": 500}

    def cancel_team_plan(self, **kwargs):
        self.calls.append(("cancel", kwargs))
        return "default-plan"

    def apply_plan_change(self, **kwargs):
        self.calls.append(("change", kwargs))
        return {"id": "sub_123"}

    def apply_team_plan_purchase(self, **kwargs):
        self.calls.append(("purchase", kwargs))

    def sync_deleted_subscription(self, **kwargs):
        self.calls.append(("deleted", kwargs))
        return "free-plan"


class FakeCheckoutContext:
    """Stub for the CheckoutContextPort dependency added in the DDD/Hex
    refactor. These delegation tests never resolve a checkout context, so it
    only needs to satisfy construction."""

    def resolve_checkout_context(self, **kwargs):
        return None, None, None


def test_team_plan_billing_service_delegates_to_store():
    store = FakeTeamPlanBillingStore()
    service = TeamPlanBillingService(store, FakeCheckoutContext())

    assert (
        service.checkout_team_plan(
            workspace="workspace",
            plan="plan",
            customer_email="owner@example.com",
            customer_name="Owner",
            user_id="user-1",
            team="team",
            success_url="https://example.com/success",
            cancel_url="https://example.com/cancel",
            proration_behavior="none",
        )
        == ({"status": "updated"}, 200)
    )
    assert service.preview_plan_change(workspace="workspace", plan="plan") == {"amount_due": 500}
    assert service.cancel_team_plan(workspace="workspace") == "default-plan"
    assert (
        service.apply_plan_change(
            workspace="workspace",
            plan="plan",
            proration_behavior="create_prorations",
        )
        == {"id": "sub_123"}
    )
    service.apply_team_plan_purchase(
        workspace="workspace",
        metadata={"plan_id": "1"},
        subscription_id="sub_123",
        customer_id="cus_123",
        period_end="period-end",
        method="method",
    )
    assert service.sync_deleted_subscription(workspace="workspace") == "free-plan"

    assert [call[0] for call in store.calls] == [
        "checkout",
        "preview",
        "cancel",
        "change",
        "purchase",
        "deleted",
    ]
