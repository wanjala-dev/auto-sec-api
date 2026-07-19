from __future__ import annotations

from components.payments.application.service import (
    TeamPlanWebhookService,
)


class FakeTeamPlanWebhookStore:
    def __init__(self):
        self.calls = []

    def handle_verified_webhook(self, **kwargs):
        self.calls.append(kwargs)


def test_team_plan_webhook_service_delegates_to_store():
    store = FakeTeamPlanWebhookStore()
    service = TeamPlanWebhookService(store)

    service.handle_verified_webhook(
        event={"type": "invoice.payment_succeeded"},
        workspace="workspace",
        method="method",
        payment_event="payment-event",
        api_key="sk_test",
    )

    assert store.calls == [
        {
            "event": {"type": "invoice.payment_succeeded"},
            "workspace": "workspace",
            "method": "method",
            "payment_event": "payment-event",
            "api_key": "sk_test",
        }
    ]
