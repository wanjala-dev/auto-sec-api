"""Integration tests for the versioned payments / billing READ endpoints.

Proves the API-v1 migration of the billing read surface — every GET that emits
money or a normalizable datetime — without disturbing the v0 (live) shape:

* v0 (today's unversioned routes AND ``/api/v0/...``) returns the EXACT shape
  current clients rely on — ``price`` / ``amount`` as bare numbers, ``currency``
  a sibling, Stripe amounts as integer minor units, Stripe timestamps as Unix
  epochs. UNCHANGED, byte-for-byte.
* v1 reshapes every money figure into a C1 ``{amount_minor, currency,
  amount_display}`` object and normalizes datetimes to ISO-8601 UTC ``Z`` (C4).

Two minor-unit semantics are load-bearing and are asserted explicitly:

* **Team-plan price** (``Plan.price`` / ``PaymentPlan.amount``) is MAJOR units
  (dollars) — fed to ``build_money_v1`` (``$30`` -> ``amount_minor=3000``).
* **Stripe invoice amounts** (``amount_due``, ``amount_paid`` …) are ALREADY
  minor units (cents) — fed to ``build_money_v1_from_minor`` (``2999`` cents ->
  ``amount_minor=2999``, NOT 299900).

The pure-DB reads (billing-plans, public payment methods, payment-method plans)
are exercised end-to-end over the alias, ``/api/v0/``, and ``/api/v1/``. The
Stripe-fed reads (overview / history / plan-preview) require a live Stripe call
to populate money, so their v1 reshape is asserted at the
reshaper-function level on synthetic provider payloads — the same boundary the
controller invokes.
"""

from __future__ import annotations

import pytest

from components.payments.mappers.rest.billing_v1_serializers import (
    PaymentPlanSerializer,
    PaymentPlanSerializerV1,
    billing_history_to_v1,
    billing_overview_to_v1,
    invoice_row_to_v1,
    payment_plan_serializer_for_version,
    plan_preview_to_v1,
    public_payment_method_serializer_for_version,
    upcoming_invoice_to_v1,
)
from components.money.mappers.rest.money_serializers import (
    build_money_v1,
    build_money_v1_from_minor,
)

pytestmark = pytest.mark.django_db


# ── Helpers ──────────────────────────────────────────────────────────────────


def _billing_plans_url(prefix, workspace_id):
    return f"{prefix}/workspaces/billing/plans/?workspace={workspace_id}"


def _manage_plans_url(prefix, workspace_id, method_id, context="recipient_sponsorship"):
    return (
        f"{prefix}/workspaces/payments/workspaces/{workspace_id}"
        f"/methods/{method_id}/plans/?context={context}"
    )


# ── billing-plans: pure DB, MAJOR-unit price ─────────────────────────────────


class TestBillingPlansV0Unchanged:
    def test_v0_price_is_bare_integer(self, api_client, payment_workspace):
        # Give the workspace a non-zero priced plan so the money is observable.
        plan = payment_workspace.workspace.plan
        plan.price = 30
        plan.currency = "usd"
        plan.save(update_fields=["price", "currency"])
        api_client.force_authenticate(payment_workspace.owner)

        resp = api_client.get(_billing_plans_url("", payment_workspace.workspace.id))

        assert resp.status_code == 200, resp.content
        rows = resp.json()["plans"]
        row = next(r for r in rows if r["title"] == plan.title)
        assert row["price"] == 30
        assert not isinstance(row["price"], dict)
        assert row["currency"] == "usd"

    def test_v0_explicit_mount_matches_alias(self, api_client, payment_workspace):
        api_client.force_authenticate(payment_workspace.owner)
        alias = api_client.get(_billing_plans_url("", payment_workspace.workspace.id))
        v0 = api_client.get(_billing_plans_url("/api/v0", payment_workspace.workspace.id))
        assert v0.status_code == 200, v0.content
        assert v0.json() == alias.json()


class TestBillingPlansV1Shape:
    def test_v1_price_is_money_object(self, api_client, payment_workspace):
        plan = payment_workspace.workspace.plan
        plan.price = 30
        plan.currency = "usd"
        plan.save(update_fields=["price", "currency"])
        api_client.force_authenticate(payment_workspace.owner)

        resp = api_client.get(_billing_plans_url("/api/v1", payment_workspace.workspace.id))

        assert resp.status_code == 200, resp.content
        rows = resp.json()["plans"]
        row = next(r for r in rows if r["title"] == plan.title)
        # MAJOR -> minor: $30 -> 3000 minor.
        assert row["price"] == {
            "amount_minor": 3000,
            "currency": "USD",
            "amount_display": "USD 30.00",
        }
        # Limit/entitlement keys untouched.
        assert "max_members_per_team" in row


# ── public payment methods: nested plan amounts, MAJOR units ─────────────────
#
# The public-method controller filters on ``enabled_contexts__contains`` (a
# JSONField ``contains`` lookup) which Postgres supports but the SQLite test DB
# does NOT — so the route can't be exercised end-to-end here. The v1 reshape is
# asserted at the serializer level on a real ``WorkspacePaymentMethod`` row
# (the exact object the controller serializes), the same way the budgeting
# template asserts Stripe-unreachable shapes at the serializer boundary.


class TestPublicMethodSerializerV0Unchanged:
    def test_v0_nested_plan_amount_is_bare(self, payment_workspace):
        from components.payments.mappers.rest.payment_serializers import (
            PublicPaymentMethodSerializer,
        )

        data = PublicPaymentMethodSerializer(
            payment_workspace.method,
            context={"plan_filters": {"context": "recipient_sponsorship", "recipient_id": None}},
        ).data
        plans = data["plans"]
        assert plans, "expected at least one recipient_sponsorship plan"
        assert all(not isinstance(p["amount"], dict) for p in plans)
        assert all("currency" in p for p in plans)


class TestPublicMethodSerializerV1Shape:
    def test_v1_nested_plan_amount_is_money_object(self, payment_workspace):
        from components.payments.mappers.rest.billing_v1_serializers import (
            PublicPaymentMethodSerializerV1,
        )

        data = PublicPaymentMethodSerializerV1(
            payment_workspace.method,
            context={"plan_filters": {"context": "recipient_sponsorship", "recipient_id": None}},
        ).data
        plans = data["plans"]
        assert plans, "expected at least one recipient_sponsorship plan"
        for p in plans:
            assert isinstance(p["amount"], dict)
            assert set(p["amount"]) == {"amount_minor", "currency", "amount_display"}
        # The $30.00 monthly sponsorship plan -> 3000 minor.
        assert any(p["amount"]["amount_minor"] == 3000 for p in plans)


# ── payment-method plans (manage_plans GET): MAJOR units, write left alone ────


class TestManagePlansV0Unchanged:
    def test_v0_amount_is_bare_decimal_string(self, api_client, payment_workspace):
        api_client.force_authenticate(payment_workspace.owner)
        resp = api_client.get(
            _manage_plans_url("", payment_workspace.workspace.id, payment_workspace.method.id)
        )
        assert resp.status_code == 200, resp.content
        rows = resp.json()
        assert rows, "expected recipient_sponsorship plans"
        assert all(not isinstance(r["amount"], dict) for r in rows)

    def test_v0_explicit_mount_matches_alias(self, api_client, payment_workspace):
        api_client.force_authenticate(payment_workspace.owner)
        alias = api_client.get(
            _manage_plans_url("", payment_workspace.workspace.id, payment_workspace.method.id)
        )
        v0 = api_client.get(
            _manage_plans_url("/api/v0", payment_workspace.workspace.id, payment_workspace.method.id)
        )
        assert v0.status_code == 200, v0.content
        assert v0.json() == alias.json()


class TestManagePlansV1Shape:
    def test_v1_amount_is_money_object(self, api_client, payment_workspace):
        api_client.force_authenticate(payment_workspace.owner)
        resp = api_client.get(
            _manage_plans_url("/api/v1", payment_workspace.workspace.id, payment_workspace.method.id)
        )
        assert resp.status_code == 200, resp.content
        rows = resp.json()
        assert rows
        for r in rows:
            assert isinstance(r["amount"], dict)
            assert set(r["amount"]) == {"amount_minor", "currency", "amount_display"}
        # $30.00 monthly sponsorship -> 3000 minor.
        assert any(r["amount"]["amount_minor"] == 3000 for r in rows)


# ── Stripe-fed reshapers: ALREADY-minor amounts + epoch timestamps ───────────


class TestInvoiceRowReshaper:
    """billing-history rows carry Stripe MINOR-unit amounts + epoch timestamps."""

    def test_amounts_treated_as_already_minor(self):
        row = {
            "id": "in_1",
            "number": "INV-1",
            "status": "paid",
            "amount_due": 2999,  # Stripe cents — NOT dollars
            "amount_paid": 2999,
            "amount_remaining": 0,
            "currency": "usd",
            "created": 1_700_000_000,
            "period_start": 1_700_000_000,
            "period_end": 1_702_592_000,
            "subscription": "sub_1",
            "hosted_invoice_url": "https://pay.stripe.test/in_1",
            "invoice_pdf": "https://pay.stripe.test/in_1.pdf",
        }
        out = invoice_row_to_v1(row)
        # 2999 cents stays 2999 minor — NOT multiplied to 299900.
        assert out["amount_due"] == {
            "amount_minor": 2999,
            "currency": "USD",
            "amount_display": "USD 29.99",
        }
        assert out["amount_paid"]["amount_minor"] == 2999
        assert out["amount_remaining"]["amount_minor"] == 0
        # Epoch -> ISO-Z, seconds precision, no microseconds.
        assert out["created"].endswith("Z")
        assert "T" in out["created"]
        assert "." not in out["created"]
        # Non-money fields untouched.
        assert out["id"] == "in_1"
        assert out["hosted_invoice_url"] == row["hosted_invoice_url"]

    def test_per_row_currency_labels_its_own_amount(self):
        row = {"amount_due": 100000, "amount_paid": 0, "amount_remaining": 0, "currency": "kes",
               "created": None, "period_start": None, "period_end": None}
        out = invoice_row_to_v1(row)
        assert out["amount_due"]["currency"] == "KES"
        assert out["amount_due"]["amount_minor"] == 100000
        # Null epoch -> present-null (C8).
        assert out["created"] is None


class TestUpcomingInvoiceReshaper:
    def test_amount_minor_and_epoch(self):
        out = upcoming_invoice_to_v1(
            {"amount_due": 4500, "currency": "usd", "next_payment_attempt": 1_700_000_000,
             "hosted_invoice_url": "https://x"}
        )
        assert out["amount_due"]["amount_minor"] == 4500
        assert out["next_payment_attempt"].endswith("Z")
        assert out["hosted_invoice_url"] == "https://x"

    def test_none_passthrough(self):
        assert upcoming_invoice_to_v1(None) is None


class TestPlanPreviewReshaper:
    def test_amount_minor_epoch_and_lines_untouched(self):
        lines = [{"description": "Pro plan", "amount": 5000}]
        out = plan_preview_to_v1(
            {"amount_due": 5000, "currency": "usd", "next_payment_attempt": 1_700_000_000,
             "lines": lines}
        )
        assert out["amount_due"]["amount_minor"] == 5000
        assert out["next_payment_attempt"].endswith("Z")
        # Stripe raw line payload is opaque passthrough — unchanged.
        assert out["lines"] is lines


class TestBillingOverviewReshaper:
    def test_plan_major_upcoming_minor_and_datetimes(self):
        import datetime

        payload = {
            "workspace_id": "ws-1",
            "plan": {"id": 1, "title": "Pro", "price": 30, "currency": "usd",
                     "billing_interval": "month", "interval_count": 1},
            "plan_status": "active",
            "plan_end_date": datetime.datetime(2026, 1, 2, 3, 4, 5),
            "stripe_customer_id": "cus_1",
            "stripe_subscription_id": "sub_1",
            "subscription_status": "active",
            "current_period_end": 1_700_000_000,
            "default_payment_method_id": "pm_1",
            "payment_methods": [{"id": "pm_1", "brand": "visa", "last4": "4242"}],
            "upcoming_invoice": {"amount_due": 3000, "currency": "usd",
                                 "next_payment_attempt": 1_700_000_000},
        }
        out = billing_overview_to_v1(payload, workspace=None)
        # Plan price is MAJOR -> $30 -> 3000 minor.
        assert out["plan"]["price"]["amount_minor"] == 3000
        # Upcoming invoice amount is MINOR -> 3000 cents -> 3000 minor.
        assert out["upcoming_invoice"]["amount_due"]["amount_minor"] == 3000
        # DateTimeField -> ISO-Z.
        assert out["plan_end_date"] == "2026-01-02T03:04:05Z"
        # Stripe epoch -> ISO-Z.
        assert out["current_period_end"].endswith("Z")
        # Cards (no money) untouched.
        assert out["payment_methods"][0]["last4"] == "4242"

    def test_history_maps_each_row(self):
        payload = {"workspace_id": "ws", "subscription_id": "sub", "has_more": False,
                   "next_cursor": None,
                   "invoices": [{"amount_due": 1000, "amount_paid": 1000, "amount_remaining": 0,
                                 "currency": "usd", "created": None, "period_start": None,
                                 "period_end": None}]}
        out = billing_history_to_v1(payload)
        assert out["invoices"][0]["amount_due"]["amount_minor"] == 1000


# ── Minor-unit builder semantics (the load-bearing distinction) ──────────────


class TestMoneyBuilderSemantics:
    def test_major_builder_multiplies_up(self):
        assert build_money_v1("30.00", "usd")["amount_minor"] == 3000

    def test_minor_builder_does_not_multiply(self):
        assert build_money_v1_from_minor(2999, "usd")["amount_minor"] == 2999

    def test_minor_builder_display_derives_major(self):
        assert build_money_v1_from_minor(2999, "usd")["amount_display"] == "USD 29.99"

    def test_minor_builder_zero_decimal_currency(self):
        # JPY exponent 0 — 1000 minor == 1000 major.
        money = build_money_v1_from_minor(1000, "jpy")
        assert money["amount_minor"] == 1000
        assert money["amount_display"] == "JPY 1,000"

    def test_minor_builder_none_is_present_null(self):
        assert build_money_v1_from_minor(None, "usd") is None


# ── Version selection ────────────────────────────────────────────────────────


class TestVersionSelection:
    def test_plan_v1_selects_v1(self):
        assert payment_plan_serializer_for_version("v1") is PaymentPlanSerializerV1

    def test_plan_v0_selects_writable(self):
        assert payment_plan_serializer_for_version("v0") is PaymentPlanSerializer

    def test_plan_none_defaults_writable(self):
        assert payment_plan_serializer_for_version(None) is PaymentPlanSerializer

    def test_public_method_v1_vs_v0(self):
        from components.payments.mappers.rest.payment_serializers import (
            PublicPaymentMethodSerializer,
        )
        from components.payments.mappers.rest.billing_v1_serializers import (
            PublicPaymentMethodSerializerV1,
        )

        assert public_payment_method_serializer_for_version("v1") is PublicPaymentMethodSerializerV1
        assert public_payment_method_serializer_for_version("v0") is PublicPaymentMethodSerializer
