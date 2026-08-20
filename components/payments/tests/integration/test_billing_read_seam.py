"""The billing / payments READ surface must resolve, and must fail honestly.

Two defects are pinned here. Both made the whole read surface unusable, and
both were invisible to the type checker because they hide behind a runtime
attribute lookup and an exception-ordering subtlety respectively.

**1. The dead provider seam (500).**
The payment ledger (``PaymentProvider`` / ``WorkspacePaymentMethod`` /
``PaymentPlan`` / ``PaymentWebhookEndpoint``) is *owned by* the payments
context but *registered under* the ``workspaces`` Django app. The controller
took the physical placement for ownership and asked
``WorkspacesModelsProvider`` for these classes. That provider never exposed
them, so every read raised::

    AttributeError: 'WorkspacesModelsProvider' object has no attribute
                    'WorkspacePaymentMethod'

`GET …/methods/`, `GET …/providers/`, `GET …/public/workspaces/<id>/` and
`GET …/providers/health/` all returned 500. They are now served by
``PaymentsModelsProvider``. Identical fork-drift, and identical fix, to the
relocated ``subscription.Plan`` pinned in ``test_billing_plan_lookup.py``.

**2. The unreachable error branch (500 instead of a typed refusal).**
``PaymentConfigurationError`` and ``SubscriptionError`` subclass
``shared_kernel.ValidationError``, which subclasses ``ValueError``. Every
billing controller caught ``ValueError`` *above* the domain-error branch, so
the domain branch was dead code at all ten call sites and an unconfigured
Stripe surfaced as a raw 5xx. That matters beyond tidiness: the frontend's
``apiClient`` counts any ``status >= 500`` as "backend unhealthy" and trips the
app-wide offline overlay after ``OFFLINE_THRESHOLD = 2`` consecutive failures —
and the billing screen fires overview + payment-methods back to back, so the
unconfigured case blacked out the entire HUD. An optional integration not being
wired is not a server fault: it is now a typed **409** the HUD can render as
"billing isn't set up".

No test here contacts Stripe. The configured case injects an in-memory fake
over the billing port; the unconfigured case is the genuine article, because
``api.settings.test`` ships ``STRIPE_SECRET_KEY = ""``.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from django.apps import apps as django_apps
from django.db import connection

from components.payments.api.billing_support import billing_error_response
from components.payments.domain.errors import (
    PaymentConfigurationError,
    SubscriptionError,
)

pytestmark = pytest.mark.django_db


OVERVIEW_URL = "/workspaces/billing/overview/"
HISTORY_URL = "/workspaces/billing/history/"
BILLING_METHODS_URL = "/workspaces/billing/payment-methods/"
PROVIDERS_URL = "/workspaces/payments/providers/"
PROVIDER_HEALTH_URL = "/workspaces/payments/providers/health/"


def _rows(resp):
    """Return the row list whether or not the endpoint paginates."""
    data = resp.data
    return data["results"] if isinstance(data, dict) and "results" in data else data


def _methods_url(workspace_id) -> str:
    return f"/workspaces/payments/workspaces/{workspace_id}/methods/"


def _public_methods_url(workspace_id) -> str:
    return f"/workspaces/payments/public/workspaces/{workspace_id}/"


@pytest.fixture
def billing_admin(api_client, workspace_factory):
    """A workspace + its owner, authenticated — owners pass the billing gate."""
    workspace = workspace_factory()
    api_client.force_authenticate(workspace.workspace_owner)
    return workspace


# ── 1. The provider seam resolves ────────────────────────────────────────────


class TestPaymentLedgerReadsResolve:
    """Every read that touches a payment-ledger model must resolve its class.

    Each of these raised ``AttributeError`` -> 500 before the fix. The
    assertion that matters is "not a 5xx"; the exact 200 body is asserted
    where it is cheap to do so.
    """

    def test_workspace_payment_methods_list_resolves(self, api_client, billing_admin, payment_method_factory):
        method = payment_method_factory(billing_admin)

        resp = api_client.get(_methods_url(billing_admin.id))

        assert resp.status_code == 200, resp.content
        returned_ids = {str(row["id"]) for row in _rows(resp)}
        assert str(method.id) in returned_ids

    def test_workspace_payment_methods_list_is_empty_not_broken(self, api_client, billing_admin):
        """No methods yet is an empty list, not an error."""
        resp = api_client.get(_methods_url(billing_admin.id))

        assert resp.status_code == 200, resp.content
        assert list(_rows(resp)) == []

    def test_provider_catalogue_resolves(self, api_client, payment_provider):
        resp = api_client.get(PROVIDERS_URL)

        assert resp.status_code == 200, resp.content
        slugs = {row["slug"] for row in _rows(resp)}
        assert "stripe" in slugs

    @pytest.mark.skipif(
        connection.vendor != "postgresql",
        reason=(
            "The public listing filters ``enabled_contexts__contains`` — a JSONField "
            "`contains` lookup Django only supports on PostgreSQL (production). The "
            "SQLite test backend raises NotSupportedError before the view is exercised, "
            "so this endpoint's provider seam is covered by TestPaymentsModelsProvider "
            "instead."
        ),
    )
    def test_public_workspace_methods_resolve(self, api_client, billing_admin, payment_method_factory):
        payment_method_factory(billing_admin)

        resp = api_client.get(_public_methods_url(billing_admin.id))

        assert resp.status_code == 200, resp.content

    def test_provider_health_is_not_shadowed_by_the_router(self, api_client, billing_admin):
        """``providers/health/`` must reach its own admin-only controller.

        ``router.register(r"providers", …)`` generates a catch-all detail route
        ``providers/<pk>/`` which matched first and dispatched this URL to
        ``PaymentProviderViewSet.retrieve(pk="health")`` -> 500. It now resolves
        to ``ProviderHealthController``, whose ``IsAdminUser`` gate refuses a
        non-admin with 403 — a refusal, not a crash.
        """
        resp = api_client.get(PROVIDER_HEALTH_URL)

        assert resp.status_code < 500, resp.content
        assert resp.status_code == 403, resp.content

    def test_provider_health_serves_an_admin(self, api_client, user_factory):
        admin = user_factory()
        admin.is_staff = True
        admin.is_superuser = True
        admin.save(update_fields=["is_staff", "is_superuser"])
        api_client.force_authenticate(admin)

        resp = api_client.get(PROVIDER_HEALTH_URL)

        assert resp.status_code == 200, resp.content
        assert isinstance(resp.data, list)


# ── 2. Stripe NOT configured -> typed 409, never a 5xx ───────────────────────


class TestBillingWithoutStripeConfigured:
    """``api.settings.test`` has no ``STRIPE_SECRET_KEY`` — the real unconfigured case.

    Fails closed (no billing data is invented) but says so in a way the HUD can
    render, and without tripping the >=500 offline overlay.
    """

    @pytest.mark.parametrize(
        "url",
        [OVERVIEW_URL, HISTORY_URL, BILLING_METHODS_URL],
        ids=["overview", "history", "payment-methods"],
    )
    def test_returns_typed_409_not_5xx(self, api_client, billing_admin, url):
        resp = api_client.get(f"{url}?workspace={billing_admin.id}")

        assert resp.status_code < 500, f"{url} -> {resp.status_code}: {resp.content}"
        assert resp.status_code == 409, resp.content
        assert resp.data["error_code"] == "PaymentConfigurationError"
        # A human-readable reason the HUD can show verbatim.
        assert resp.data["detail"]
        assert resp.data["error"]

    def test_does_not_leak_a_secret_or_invent_billing_data(self, api_client, billing_admin):
        resp = api_client.get(f"{OVERVIEW_URL}?workspace={billing_admin.id}")

        # Refusal carries no billing payload — no empty-list lie that would
        # render as "you have no payment methods" when the truth is "we never
        # asked".
        assert "payment_methods" not in resp.data
        assert "upcoming_invoice" not in resp.data
        assert set(resp.data) == {"error", "error_code", "detail"}

    def test_the_valueerror_branch_no_longer_shadows_the_domain_branch(self):
        """Why the ordering in every controller ladder is load-bearing.

        If this stops being true the ladders could be reordered harmlessly —
        but while it holds, ``except ValueError`` above the domain branch
        silently swallows a configuration error into a 500.
        """
        assert issubclass(PaymentConfigurationError, ValueError)
        assert issubclass(SubscriptionError, ValueError)


# ── 3. Stripe IS configured -> 200 + sane body (in-memory fake, never Stripe) ─


class _FakeBillingStore:
    """In-memory stand-in for ``WorkspaceBillingPort``.

    Returns the shapes the controller reads. No network, no Stripe SDK.
    """

    CONTEXT = SimpleNamespace(customer_id="cus_fake_001", subscription_id="sub_fake_001")

    def get_context(self, *, workspace):
        return self.CONTEXT

    def fetch_customer(self, *, customer_id):
        return {"id": customer_id, "invoice_settings": {"default_payment_method": "pm_fake_001"}}

    def fetch_subscription(self, *, subscription_id):
        return {"id": subscription_id, "status": "active", "current_period_end": 1_800_000_000}

    def resolve_default_payment_method_id(self, *, subscription, customer):
        return "pm_fake_001"

    def list_payment_methods(self, *, customer_id):
        return [{"id": "pm_fake_001", "card": {"brand": "visa", "last4": "4242", "exp_month": 1, "exp_year": 2030}}]

    def preview_upcoming_invoice(self, *, customer_id, subscription_id):
        return {"amount_due": 2999, "currency": "usd", "next_payment_attempt": 1_800_000_000}

    def list_invoices(self, *, customer_id, subscription_id, limit, starting_after, ending_before):
        return (
            [
                {
                    "id": "in_fake_001",
                    "created": 1_700_000_000,
                    "amount_due": 2999,
                    "amount_paid": 2999,
                    "currency": "usd",
                    "status": "paid",
                    "lines": {"data": []},
                }
            ],
            False,
        )


@pytest.fixture
def stripe_configured(monkeypatch):
    """Swap the controller's billing service onto an in-memory store.

    Patches the port implementation rather than the service, so the real
    ``WorkspaceBillingService`` orchestration under test still runs.
    """
    from components.payments.api import controller as payments_controller
    from components.payments.application.service import WorkspaceBillingService

    monkeypatch.setattr(
        payments_controller,
        "workspace_billing_service",
        WorkspaceBillingService(billing_store=_FakeBillingStore()),
    )


class TestBillingWithStripeConfigured:
    def test_overview_returns_a_sane_body(self, api_client, billing_admin, stripe_configured):
        resp = api_client.get(f"{OVERVIEW_URL}?workspace={billing_admin.id}")

        assert resp.status_code == 200, resp.content
        assert resp.data["workspace_id"] == str(billing_admin.id)
        assert resp.data["subscription_status"] == "active"
        assert resp.data["default_payment_method_id"] == "pm_fake_001"
        assert len(resp.data["payment_methods"]) == 1
        assert resp.data["upcoming_invoice"] is not None

    def test_history_returns_a_sane_body(self, api_client, billing_admin, stripe_configured):
        resp = api_client.get(f"{HISTORY_URL}?workspace={billing_admin.id}")

        assert resp.status_code == 200, resp.content
        assert resp.data["workspace_id"] == str(billing_admin.id)
        assert len(resp.data["invoices"]) == 1
        assert resp.data["has_more"] is False

    def test_payment_methods_returns_a_sane_body(self, api_client, billing_admin, stripe_configured):
        resp = api_client.get(f"{BILLING_METHODS_URL}?workspace={billing_admin.id}")

        assert resp.status_code == 200, resp.content
        assert resp.data["default_payment_method_id"] == "pm_fake_001"
        assert len(resp.data["payment_methods"]) == 1


# ── 4. The canonical error mapping ───────────────────────────────────────────


class TestBillingErrorResponseMapping:
    """ONE mapping for the whole billing surface, so status can't drift again."""

    def test_configuration_error_is_a_typed_409(self):
        resp = billing_error_response(PaymentConfigurationError("Stripe payment provider is not configured."))

        assert resp.status_code == 409
        assert resp.data["error_code"] == "PaymentConfigurationError"
        assert resp.data["detail"] == "Billing is not configured for this deployment."

    def test_subscription_error_stays_a_502(self):
        """Stripe IS configured but the upstream call failed — genuinely a bad
        gateway, and genuinely a backend-unhealthy signal."""
        resp = billing_error_response(SubscriptionError("Unable to load Stripe subscription."))

        assert resp.status_code == 502
        assert resp.data["error_code"] == "SubscriptionError"


# ── 5. The provider itself ───────────────────────────────────────────────────


class TestPaymentsModelsProvider:
    """Guard the seam directly: the provider must serve every ledger model the
    API layer asks it for, and they must be the ``workspaces``-app classes."""

    @pytest.mark.parametrize(
        "attr",
        ["PaymentProvider", "WorkspacePaymentMethod", "PaymentPlan", "PaymentWebhookEndpoint"],
    )
    def test_serves_the_workspaces_app_model(self, attr):
        from components.payments.application.providers.payments_models_provider import (
            get_payments_models_provider,
        )

        model = getattr(get_payments_models_provider(), attr)

        assert model is django_apps.get_model("workspaces", attr)

    def test_workspaces_provider_still_does_not_serve_ledger_models(self):
        """Documents the boundary: app registration is a persistence detail;
        ownership decides the provider. Asking the workspace context for a
        payments model is the bug this suite exists for."""
        from components.workspace.application.providers.workspaces_models_provider import (
            get_workspaces_models_provider,
        )

        assert not hasattr(get_workspaces_models_provider(), "WorkspacePaymentMethod")
