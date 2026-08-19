"""A dedicated tenant's OWN subscription event must bill that tenant, not the pool.

THE BUG THIS PINS. ``/workspaces/billing/stripe/webhook/`` is the only mounted
Stripe route in this fork, and it carries our SaaS revenue — the tenant's own
subscription to autosec. Stripe POSTs it to one fixed URL with no tenant
subdomain, so ``TenantHostMiddleware`` binds the pooled console.

PR #388 taught the webhook to bind the owning tenant, but only via the
**connected account** (``resolve_db_alias_for_stripe_account``). A platform
event carries no connected account — only a customer, a subscription, and (on
checkout) our own ``workspace_id`` metadata — so that resolver answered
``None`` on every single delivery to this endpoint and nothing ever rebound.
The consequence, watched failing before the fix:

    the ``PaymentEvent`` ledger row landed in ``default`` (the pool);
    ``Workspace.objects.filter(...)`` looked for a DEDICATED tenant's workspace
    in the pool, found nothing, marked the event
    "Missing workspace for Stripe webhook" — and returned **200**.

200 tells Stripe the event was handled. It is never retried. A dedicated
tenant simply stops being billed, and nothing anywhere says so.

These tests count rows in BOTH databases, because that is the only assertion
that can tell "wrote to the tenant" from "wrote to the pool". ``tenant_probe``
is a real second SQLite file (see ``api/settings/test.py``); the older extra
aliases all mirror ``default`` and would prove nothing.

They drive the REAL URL through the REAL controller, because the HTTP status
code is half the fix: an event we cannot attribute must come back 5xx
(retryable, visible in Stripe's dashboard), never 2xx.
"""

from __future__ import annotations

import json
import logging

import pytest
from django.apps import apps as django_apps

from components.payments.tests._helpers.stripe_webhook_signing import (
    make_event,
    stripe_signed_headers,
)
from infrastructure.persistence.workspaces.payments.models import PaymentEvent

WEBHOOK_PATH = "/workspaces/billing/stripe/webhook/"
SECRET = "whsec_platform_billing_tenant_routing_probe"
TENANT_ALIAS = "tenant_probe"
REAL_ROUTER = ["components.shared_platform.infrastructure.tenancy.router.TenantRouter"]

DEDICATED_CUSTOMER = "cus_dedicated_faura_probe_001"
DEDICATED_SUBSCRIPTION = "sub_dedicated_faura_probe_001"
POOLED_CUSTOMER = "cus_pooled_probe_001"
POOLED_SUBSCRIPTION = "sub_pooled_probe_001"
ORPHAN_CUSTOMER = "cus_no_database_claims_this_001"
ORPHAN_SUBSCRIPTION = "sub_no_database_claims_this_001"

pytestmark = pytest.mark.django_db(databases=["default", TENANT_ALIAS])


@pytest.fixture(autouse=True)
def no_stripe_network(monkeypatch):
    """Any real Stripe HTTP call fails the test rather than reaching the internet.

    The event types below are chosen so the handler makes none — this fixture
    is what proves that stays true instead of merely being believed.
    """
    import stripe.api_requestor

    def _forbidden(*args, **kwargs):  # pragma: no cover - only fires on regression
        raise AssertionError("a test made a real Stripe API call")

    monkeypatch.setattr(stripe.api_requestor.APIRequestor, "request_raw", _forbidden)


@pytest.fixture
def platform_webhook_settings(settings):
    settings.DATABASE_ROUTERS = REAL_ROUTER
    settings.STRIPE_WEBHOOK_KEY = SECRET
    settings.STRIPE_CONNECT_WEBHOOK_SECRET = SECRET
    settings.STRIPE_SUBSCRIPTIONS_WEBHOOK_SECRET = SECRET
    settings.STRIPE_SECRET_KEY = "sk_test_platform_billing_tenant_routing_probe"
    return settings


def _make_workspace(*, alias: str | None, username: str, customer: str, subscription: str):
    """Seed a workspace the way its tier really seeds one (tenancy skill §8).

    ``alias=None`` means the pooled console. Anything else binds that dedicated
    database first, so everything the writes drag along (the ``UserProfile`` a
    ``post_save`` bridge creates, for one) follows the binding — which explicit
    ``.using()`` calls would not.
    """
    from django.contrib.auth import get_user_model

    from components.shared_platform.infrastructure.tenancy.context import (
        KIND_DEDICATED,
        TenantContext,
        pooled_context,
        tenant_context,
    )

    Workspace = django_apps.get_model("workspaces", "Workspace")
    user_model = get_user_model()

    scope = (
        pooled_context()
        if alias is None
        else tenant_context(TenantContext(kind=KIND_DEDICATED, tenant_id="probe", subdomain="probe", db_alias=alias))
    )
    with scope:
        owner = user_model.objects.create(username=username, email=f"{username}@probe.test")
        return Workspace.objects.create(
            workspace_name=f"Probe {username}",
            workspace_owner=owner,
            stripe_customer_id=customer,
            stripe_subscription_id=subscription,
            plan_status="canceled",
            # ``WorkspaceManager`` filters ``status="active"`` and the model
            # default is "inactive" — an inactive workspace is invisible to
            # every ``Workspace.objects`` lookup the webhook makes.
            status="active",
        )


@pytest.fixture
def dedicated_workspace(platform_webhook_settings):
    return _make_workspace(
        alias=TENANT_ALIAS,
        username="probe-dedicated-owner",
        customer=DEDICATED_CUSTOMER,
        subscription=DEDICATED_SUBSCRIPTION,
    )


@pytest.fixture
def pooled_workspace(platform_webhook_settings):
    return _make_workspace(
        alias=None,
        username="probe-pooled-owner",
        customer=POOLED_CUSTOMER,
        subscription=POOLED_SUBSCRIPTION,
    )


def _subscription_updated(event_id: str, *, customer: str, subscription: str) -> bytes:
    """A ``customer.subscription.updated`` platform delivery.

    Picked because it is a real money-path event (it is in the handler map, so
    it re-applies the plan) that needs no Stripe API round trip: the handler
    reads the period end straight off the event object.
    """
    event = make_event(
        event_id=event_id,
        event_type="customer.subscription.updated",
        data_object={
            "id": subscription,
            "object": "subscription",
            "status": "active",
            "customer": customer,
            "items": {"data": []},
            "metadata": {"ctx": "team_plan"},
        },
    )
    return json.dumps(event).encode("utf-8")


def _post(api_client, payload: bytes):
    return api_client.post(
        WEBHOOK_PATH,
        data=payload,
        content_type="application/json",
        **stripe_signed_headers(payload, SECRET),
    )


def _ledger_counts(event_id: str) -> tuple[int, int]:
    """(rows in the tenant database, rows in the pool) for one event id."""
    in_tenant = PaymentEvent.objects.using(TENANT_ALIAS).filter(provider="stripe", event_id=event_id).count()
    in_pool = PaymentEvent.objects.using("default").filter(provider="stripe", event_id=event_id).count()
    return in_tenant, in_pool


class TestADedicatedTenantsSubscriptionEventBillsThatTenant:
    def test_the_ledger_row_lands_in_the_tenant_database_and_not_the_pool(
        self, api_client, platform_webhook_settings, dedicated_workspace
    ):
        """The drop proof. Watched failing on ``origin/main`` as (0, 1) + 200."""
        event_id = "evt_platform_billing_dedicated_001"

        response = _post(
            api_client,
            _subscription_updated(event_id, customer=DEDICATED_CUSTOMER, subscription=DEDICATED_SUBSCRIPTION),
        )

        assert response.status_code == 200, response.content
        in_tenant, in_pool = _ledger_counts(event_id)
        assert (in_tenant, in_pool) == (1, 0), (
            f"cross-tenant write: {TENANT_ALIAS}={in_tenant} default={in_pool} — "
            "a dedicated tenant's subscription event must never land in the pool"
        )

    def test_the_subscription_is_actually_applied_to_the_tenants_workspace(
        self, api_client, platform_webhook_settings, dedicated_workspace
    ):
        """Binding without processing would still be a billing outage.

        Before the fix the handler looked for this workspace in the pool, did
        not find it, and marked the event ignored — the workspace stayed
        ``past_due`` forever while Stripe reported the subscription active.
        """
        Workspace = django_apps.get_model("workspaces", "Workspace")
        event_id = "evt_platform_billing_applied_001"

        _post(
            api_client,
            _subscription_updated(event_id, customer=DEDICATED_CUSTOMER, subscription=DEDICATED_SUBSCRIPTION),
        )

        refreshed = Workspace.objects.using(TENANT_ALIAS).get(id=dedicated_workspace.id)
        assert refreshed.plan_status == "active"

        row = PaymentEvent.objects.using(TENANT_ALIAS).get(provider="stripe", event_id=event_id)
        assert row.status == PaymentEvent.STATUS_PROCESSED, row.status_message

    def test_a_replayed_delivery_stays_idempotent_inside_the_tenant_database(
        self, api_client, platform_webhook_settings, dedicated_workspace
    ):
        """A ledger that dedupes in the wrong database is not a ledger."""
        event_id = "evt_platform_billing_replay_001"
        payload = _subscription_updated(event_id, customer=DEDICATED_CUSTOMER, subscription=DEDICATED_SUBSCRIPTION)

        first = _post(api_client, payload)
        second = _post(api_client, payload)

        assert first.status_code == 200, first.content
        assert second.status_code == 200, second.content
        assert _ledger_counts(event_id) == (1, 0)

    def test_the_workspace_id_metadata_routes_before_any_customer_is_stamped(
        self, api_client, platform_webhook_settings, dedicated_workspace
    ):
        """The first event of a subscription's life must route too.

        ``checkout.session.completed`` is what STAMPS the customer/subscription
        onto the workspace, so those rungs cannot be what routes it. Our own
        ``workspace_id`` checkout metadata is the top rung for exactly this.
        """
        event_id = "evt_platform_billing_checkout_metadata_001"
        event = make_event(
            event_id=event_id,
            event_type="checkout.session.expired",
            data_object={
                "id": "cs_test_platform_billing_probe",
                "object": "checkout.session",
                "customer": "cus_not_yet_stamped_anywhere_001",
                "metadata": {"ctx": "team_plan", "workspace_id": str(dedicated_workspace.id)},
            },
        )
        payload = json.dumps(event).encode("utf-8")

        response = _post(api_client, payload)

        assert response.status_code == 200, response.content
        assert _ledger_counts(event_id) == (1, 0)


class TestThePooledPathIsUnchanged:
    def test_a_pooled_workspaces_subscription_event_still_resolves_to_the_pool(
        self, api_client, platform_webhook_settings, pooled_workspace
    ):
        """Most workspaces are pooled; their events already worked by accident.

        They now work on purpose — the resolver finds them in ``default`` and
        binds the pool explicitly — and the observable outcome is identical.
        """
        Workspace = django_apps.get_model("workspaces", "Workspace")
        event_id = "evt_platform_billing_pooled_001"

        response = _post(
            api_client,
            _subscription_updated(event_id, customer=POOLED_CUSTOMER, subscription=POOLED_SUBSCRIPTION),
        )

        assert response.status_code == 200, response.content
        assert _ledger_counts(event_id) == (0, 1)
        assert Workspace.objects.using("default").get(id=pooled_workspace.id).plan_status == "active"

    def test_an_event_naming_nothing_routable_is_recorded_in_the_pool_as_before(
        self, api_client, platform_webhook_settings
    ):
        """No claims → nothing to resolve → the pre-existing behaviour, untouched.

        ``customer.subscription.created`` is not in the handler map and this
        payload names no customer, so there is no tenant to find and no
        billing consequence to failing to find one. Guards the existing
        ``test_stripe_team_plan_webhook_signed_e2e`` contract.
        """
        event_id = "evt_platform_billing_no_claims_001"
        event = make_event(
            event_id=event_id,
            event_type="customer.subscription.created",
            data_object={"id": "sub_no_claims_probe", "object": "subscription", "metadata": {}},
        )

        response = _post(api_client, json.dumps(event).encode("utf-8"))

        assert response.status_code == 200, response.content
        assert _ledger_counts(event_id) == (0, 1)


class TestAnUnresolvableCustomerFailsLoudly:
    def test_it_returns_503_and_writes_nothing_anywhere(
        self, api_client, platform_webhook_settings, dedicated_workspace, caplog
    ):
        """5xx, not 2xx — and not a guess at a database either.

        2xx would be the silent drop we are removing, wearing a different hat.
        4xx would be a lie: the scan cannot distinguish "unknown customer"
        from "that tenant's database was unreachable" or "the checkout that
        stamps this customer has not committed yet", and both of those heal on
        Stripe's retry schedule.
        """
        event_id = "evt_platform_billing_unroutable_001"

        with caplog.at_level(logging.ERROR, logger="components.payments"):
            response = _post(
                api_client,
                _subscription_updated(event_id, customer=ORPHAN_CUSTOMER, subscription=ORPHAN_SUBSCRIPTION),
            )

        assert response.status_code == 503, response.content
        assert response["Retry-After"] == "60"
        assert response.json()["code"] == "tenant_unresolved"
        assert _ledger_counts(event_id) == (0, 0), "an unroutable event must not be recorded on a guess"

        records = [r for r in caplog.records if "stripe_subscription_webhook_unroutable" in r.getMessage()]
        assert records, "the drop must be recorded loudly, not merely returned"
        assert event_id in records[0].getMessage()
        assert ORPHAN_CUSTOMER in records[0].getMessage()

    def test_an_ambiguous_claim_is_refused_rather_than_guessed(
        self, api_client, platform_webhook_settings, dedicated_workspace
    ):
        """Two databases claiming one customer is a data fault, not a coin toss.

        Picking either one would bill the wrong customer — strictly worse than
        the drop this PR removes.
        """
        Workspace = django_apps.get_model("workspaces", "Workspace")
        Workspace.objects.using("default").filter(
            id=_make_workspace(
                alias=None,
                username="probe-ambiguous-owner",
                customer=DEDICATED_CUSTOMER,
                subscription=DEDICATED_SUBSCRIPTION,
            ).id
        ).update(stripe_customer_id=DEDICATED_CUSTOMER)

        event_id = "evt_platform_billing_ambiguous_001"
        response = _post(
            api_client,
            _subscription_updated(event_id, customer=DEDICATED_CUSTOMER, subscription=DEDICATED_SUBSCRIPTION),
        )

        assert response.status_code == 503, response.content
        assert _ledger_counts(event_id) == (0, 0)
