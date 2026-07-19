from __future__ import annotations

from components.payments.application.service import (
    WorkspaceBillingService,
)
from components.payments.application.ports.workspace_billing_port import WorkspaceBillingContext


class FakeWorkspaceBillingStore:
    def __init__(self):
        self.calls = []

    def get_context(self, *, workspace):
        self.calls.append(("get_context", workspace))
        return WorkspaceBillingContext(customer_id="cus_123", subscription_id="sub_123")

    def fetch_customer(self, *, customer_id):
        self.calls.append(("fetch_customer", customer_id))
        return {"id": customer_id, "invoice_settings": {"default_payment_method": "pm_default"}}

    def fetch_subscription(self, *, subscription_id):
        self.calls.append(("fetch_subscription", subscription_id))
        if not subscription_id:
            return None
        return {
            "id": subscription_id,
            "status": "active",
            "current_period_end": 1700000000,
            "default_payment_method": "pm_default",
        }

    def list_payment_methods(self, *, customer_id):
        self.calls.append(("list_payment_methods", customer_id))
        return [
            {
                "id": "pm_default",
                "customer": customer_id,
                "card": {
                    "brand": "visa",
                    "last4": "4242",
                    "exp_month": 12,
                    "exp_year": 2030,
                },
            }
        ]

    def list_invoices(
        self,
        *,
        customer_id,
        subscription_id,
        limit,
        starting_after,
        ending_before,
    ):
        self.calls.append(
            ("list_invoices", customer_id, subscription_id, limit, starting_after, ending_before)
        )
        return (
            [
                {
                    "id": "in_123",
                    "status": "paid",
                    "amount_due": 500,
                    "amount_paid": 500,
                    "amount_remaining": 0,
                    "currency": "usd",
                    "created": 1700000000,
                    "period_start": 1700000000,
                    "period_end": 1702592000,
                    "subscription": "sub_123",
                    "hosted_invoice_url": "https://example.com/invoice",
                    "invoice_pdf": "https://example.com/invoice.pdf",
                }
            ],
            False,
        )

    def preview_upcoming_invoice(self, *, customer_id, subscription_id):
        self.calls.append(("preview_upcoming_invoice", customer_id, subscription_id))
        return {
            "amount_due": 500,
            "currency": "usd",
            "next_payment_attempt": 1700001234,
            "hosted_invoice_url": "https://example.com/upcoming",
        }

    def create_setup_intent(self, *, customer_id):
        self.calls.append(("create_setup_intent", customer_id))
        return {"client_secret": "seti_secret"}

    def retrieve_payment_method(self, *, payment_method_id):
        self.calls.append(("retrieve_payment_method", payment_method_id))
        return {"id": payment_method_id, "customer": "cus_123"}

    def set_default_payment_method(self, *, customer_id, payment_method_id, subscription_id):
        self.calls.append(("set_default_payment_method", customer_id, payment_method_id, subscription_id))

    def detach_payment_method(self, *, payment_method_id):
        self.calls.append(("detach_payment_method", payment_method_id))

    def resolve_default_payment_method_id(self, *, subscription, customer):
        self.calls.append(("resolve_default_payment_method_id", subscription["id"] if subscription else None))
        return "pm_default"

    def get_publishable_key(self):
        self.calls.append(("get_publishable_key",))
        return "pk_test"


def test_workspace_billing_service_builds_overview_payload():
    service = WorkspaceBillingService(FakeWorkspaceBillingStore())

    payload = service.get_overview(workspace="workspace")

    assert payload["context"].customer_id == "cus_123"
    assert payload["default_payment_method_id"] == "pm_default"
    assert payload["payment_methods"][0]["is_default"] is True
    assert payload["upcoming_invoice"]["amount_due"] == 500


def test_workspace_billing_service_returns_history_payload():
    service = WorkspaceBillingService(FakeWorkspaceBillingStore())

    payload = service.get_history(
        workspace="workspace",
        limit=10,
        starting_after=None,
        ending_before=None,
    )

    assert payload["invoices"][0]["id"] == "in_123"
    assert payload["has_more"] is False
    assert payload["next_cursor"] is None


def test_workspace_billing_service_creates_setup_intent_payload():
    service = WorkspaceBillingService(FakeWorkspaceBillingStore())

    payload = service.create_setup_intent(workspace="workspace")

    assert payload["client_secret"] == "seti_secret"
    assert payload["customer_id"] == "cus_123"
    assert payload["publishable_key"] == "pk_test"


def test_workspace_billing_service_detaches_non_default_method():
    service = WorkspaceBillingService(FakeWorkspaceBillingStore())

    payload = service.detach_payment_method(
        workspace="workspace",
        payment_method_id="pm_other",
    )

    assert payload == {"status": "removed"}
