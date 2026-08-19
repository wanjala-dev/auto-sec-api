"""The paid-upgrade path must be able to look a Plan up.

Every billing endpoint that names a tier — list the catalogue, preview a
change, start a checkout, apply a change — first has to resolve a
``subscription.Plan`` row. That lookup used to be asked of the *team*
context's models provider, which has never exposed ``Plan``: the model was
relocated to ``infrastructure.persistence.subscription`` (its canonical
home) and the team façade was never given the attribute. Every one of the
four endpoints therefore raised ``AttributeError: 'TeamModelsProvider'
object has no attribute 'Plan'`` and returned 500 — a customer could not
see prices, preview, buy, or change a plan at all.

These tests pin the seam end-to-end and are deliberately Stripe-free: each
endpoint is driven only as far as it needs to go to prove the Plan lookup
resolved (a found plan, or an honest 404 for an unknown one) before any
payment provider is contacted.
"""

from __future__ import annotations

import pytest
from django.apps import apps as django_apps

pytestmark = pytest.mark.django_db


PLANS_URL = "/workspaces/billing/plans/"
PREVIEW_URL = "/workspaces/billing/plan/preview/"
CHECKOUT_URL = "/workspaces/billing/plan/checkout/"
CHANGE_URL = "/workspaces/billing/plan/change/"

UNKNOWN_PLAN_ID = 99_999_999


@pytest.fixture
def billing_admin(api_client, workspace_factory):
    """A workspace + its owner, authenticated — owners pass the billing admin gate."""
    workspace = workspace_factory()
    api_client.force_authenticate(workspace.workspace_owner)
    return workspace


def _make_plan(title: str, *, price: int = 0, is_default: bool = False):
    Plan = django_apps.get_model("subscription", "Plan")
    return Plan.objects.create(title=title, price=price, is_default=is_default, limits={})


class TestBillingPlanCatalogue:
    """GET /workspaces/billing/plans/ — the price list the upgrade UI reads."""

    def test_lists_the_seeded_tiers(self, api_client, billing_admin):
        _make_plan("Pro", price=25)
        _make_plan("Premium", price=79)

        resp = api_client.get(f"{PLANS_URL}?workspace={billing_admin.id}")

        assert resp.status_code == 200, resp.content
        titles = {row["title"] for row in resp.data["plans"]}
        assert {"Pro", "Premium"} <= titles
        prices = {row["title"]: row["price"] for row in resp.data["plans"]}
        assert prices["Pro"] == 25
        assert prices["Premium"] == 79


class TestPlanResolutionOnMutatingEndpoints:
    """The three tier-naming endpoints must resolve a Plan, not explode."""

    def test_preview_reaches_the_subscription_check(self, api_client, billing_admin):
        # A real plan resolves, so the controller proceeds to the next gate:
        # the workspace has no Stripe subscription to preview against. Getting
        # this 400 (rather than a 500) is the proof the lookup worked — and it
        # happens before any Stripe call.
        plan = _make_plan("Pro", price=25)

        resp = api_client.get(f"{PREVIEW_URL}?workspace={billing_admin.id}&plan_id={plan.pk}")

        assert resp.status_code == 400, resp.content
        assert "No active subscription" in resp.data["error"]

    def test_checkout_reports_an_unknown_plan_as_404(self, api_client, billing_admin):
        resp = api_client.post(
            CHECKOUT_URL,
            {"workspace": str(billing_admin.id), "plan_id": UNKNOWN_PLAN_ID},
            format="json",
        )

        assert resp.status_code == 404, resp.content
        assert resp.data["error"] == "Plan not found."

    def test_change_reports_an_unknown_plan_as_404(self, api_client, billing_admin):
        resp = api_client.post(
            CHANGE_URL,
            {"workspace": str(billing_admin.id), "plan_id": UNKNOWN_PLAN_ID},
            format="json",
        )

        assert resp.status_code == 404, resp.content
        assert resp.data["error"] == "Plan not found."


class TestResolveBillingPlan:
    """The shared resolver accepts every shape the clients actually send."""

    def test_resolves_by_int_id_digit_string_and_title(self, db):
        from components.payments.api.billing_support import _resolve_billing_plan

        pro = _make_plan("Pro", price=25)

        assert _resolve_billing_plan(pro.pk) == pro
        assert _resolve_billing_plan(str(pro.pk)) == pro
        assert _resolve_billing_plan("pro") == pro  # title match is case-insensitive

    def test_returns_none_for_unknown_or_empty(self, db):
        from components.payments.api.billing_support import _resolve_billing_plan

        assert _resolve_billing_plan(UNKNOWN_PLAN_ID) is None
        assert _resolve_billing_plan("Nonexistent") is None
        assert _resolve_billing_plan(None) is None
