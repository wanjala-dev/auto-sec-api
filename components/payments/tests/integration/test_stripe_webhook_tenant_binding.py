"""The money path must write to the tenant that owns the event — not the pool.

THE BUG THIS PINS. A payment provider POSTs to one fixed URL. There is no
tenant subdomain on that request, so ``TenantHostMiddleware`` binds the shared
(pooled) console. A Stripe **Connect** event, though, belongs to whichever
customer owns the connected account named in its signed body — and for a
DEDICATED tenant that customer's rows live in a different database.

The webhook path knew this: it resolved the owning alias with
``resolve_db_alias_for_stripe_account()`` and then called
``set_db_for_router(db_alias)``. That function wrote
``THREAD_LOCAL.DB``. The live ``TenantRouter`` reads a ``contextvars.ContextVar``
and contains no reference to that thread-local — so the call bound nothing, and
every unqualified ORM statement in the request kept routing to the pool. Both
behaviours sat side by side: the one query carrying an explicit
``.using(db_alias)`` found the right method, and the ``PaymentEvent`` written
immediately afterwards landed in the pooled database.

These tests count rows in BOTH databases, because that is the only assertion
that can tell "wrote to the tenant" from "wrote to the pool". ``tenant_probe``
is a real second SQLite file (see ``api/settings/test.py``) — the older extra
aliases all mirror ``default`` and would prove nothing.

Scope note, so the next reader is not misled: the Connect/donations webhook URL
is NOT mounted in this fork (it was stripped with the nonprofit domain), so the
proof drives the verify → bind → record sequence directly rather than over HTTP.
That sequence is exactly what ``StripeSubscriptionWebhookController.post``
executes; the live platform endpoint's own end-to-end coverage lives in
``test_stripe_team_plan_webhook_signed_e2e.py``.
"""

from __future__ import annotations

import json

import pytest
from django.apps import apps as django_apps
from django.test import RequestFactory

from components.payments.application.providers.payment_runtime_provider import (
    make_payment_runtime_provider,
)
from components.payments.application.providers.webhook_tenant_binding_provider import (
    resolve_webhook_tenant_alias,
    webhook_tenant_scope,
    webhook_write_alias,
)
from components.payments.tests._helpers.stripe_webhook_signing import (
    make_event as _make_event,
)
from components.payments.tests._helpers.stripe_webhook_signing import (
    stripe_signed_headers as _stripe_signed_headers,
)
from components.shared_kernel.application.transactional import atomic
from infrastructure.persistence.workspaces.payments.models import PaymentEvent

TENANT_ALIAS = "tenant_probe"
TENANT_ACCOUNT = "acct_dedicated_tenant_probe_001"
UNKNOWN_ACCOUNT = "acct_no_database_claims_this_001"
SECRET = "whsec_tenant_binding_probe_secret"
REAL_ROUTER = ["components.shared_platform.infrastructure.tenancy.router.TenantRouter"]

pytestmark = pytest.mark.django_db(databases=["default", TENANT_ALIAS])


@pytest.fixture
def dedicated_tenant_stripe_method(stripe_webhook_settings, django_user_model):
    """A live Stripe method whose rows exist ONLY in the dedicated tenant's DB.

    Built the way a dedicated tenant is really seeded (tenancy skill §8): bind
    the tenant, then create normally. Everything the writes drag along — the
    ``UserProfile`` a ``post_save`` bridge creates, for one — follows the
    binding, which explicit ``.using()`` calls would not.
    """
    from components.shared_platform.infrastructure.tenancy.context import (
        KIND_DEDICATED,
        TenantContext,
        tenant_context,
    )

    Workspace = django_apps.get_model("workspaces", "Workspace")
    PaymentProvider = django_apps.get_model("workspaces", "PaymentProvider")
    WorkspacePaymentMethod = django_apps.get_model("workspaces", "WorkspacePaymentMethod")

    dedicated = TenantContext(
        kind=KIND_DEDICATED,
        tenant_id="probe",
        subdomain="probe",
        db_alias=TENANT_ALIAS,
    )
    with tenant_context(dedicated):
        owner = django_user_model.objects.create(
            username="probe-tenant-owner",
            email="owner@probe-tenant.test",
        )
        workspace = Workspace.objects.create(
            workspace_name="Probe Dedicated Tenant",
            workspace_owner=owner,
        )
        provider = PaymentProvider.objects.create(
            slug="stripe",
            display_name="Stripe",
            provider_type=PaymentProvider.API,
        )
        return WorkspacePaymentMethod.objects.create(
            workspace=workspace,
            provider=provider,
            display_name="Probe Stripe",
            status=WorkspacePaymentMethod.STATUS_ACTIVE,
            provider_account_id=TENANT_ACCOUNT,
        )


def _connect_request(event_id: str, account: str):
    """A signed Connect delivery, as Stripe sends it: account in the BODY only.

    Stripe does not send a ``Stripe-Account`` request header on webhooks — the
    connected account is a field of the signed event. That is why the owning
    database cannot be known before the signature is checked, and why the
    binding is two-phase.
    """
    event = _make_event(event_id)
    event["account"] = account
    payload = json.dumps(event).encode("utf-8")
    return RequestFactory().post(
        "/payments/stripe/webhook/",
        data=payload,
        content_type="application/json",
        **_stripe_signed_headers(payload, SECRET),
    )


def _handle(request, endpoint_name: str = "donations"):
    """The controller's verify → bind → record sequence, verbatim."""
    runtime = make_payment_runtime_provider()

    hint_alias = resolve_webhook_tenant_alias(request.META.get("HTTP_STRIPE_ACCOUNT") or request.GET.get("account"))
    with webhook_tenant_scope(hint_alias):
        verification = runtime.verify_webhook(request, endpoint_name=endpoint_name)

    db_alias = verification.db_alias or hint_alias
    with webhook_tenant_scope(db_alias), atomic(using=webhook_write_alias()):
        intake = (
            runtime.record_and_claim_webhook_event(
                verification,
                claimed_by="tests.stripe_webhook_tenant_binding",
                claim_message="Webhook received.",
            )
            if verification.recordable
            else None
        )
    return verification, intake


@pytest.fixture
def stripe_webhook_settings(settings):
    settings.DATABASE_ROUTERS = REAL_ROUTER
    settings.STRIPE_WEBHOOK_KEY = SECRET
    settings.STRIPE_CONNECT_WEBHOOK_SECRET = SECRET
    settings.STRIPE_CONNECT_DONATIONS_WEBHOOK_SECRET = SECRET
    settings.STRIPE_SECRET_KEY = "sk_test_tenant_binding_probe"
    return settings


class TestAConnectEventIsWrittenToTheTenantThatOwnsIt:
    def test_the_ledger_row_lands_in_the_tenant_database_and_not_the_pool(
        self, stripe_webhook_settings, dedicated_tenant_stripe_method
    ):
        """The leak proof. Count the row in BOTH databases.

        Before the binding was made real this asserted the exact opposite of
        what happened: 0 rows in the tenant's database, 1 row in the pool.
        """
        event_id = "evt_tenant_binding_leak_probe_001"

        verification, intake = _handle(_connect_request(event_id, TENANT_ACCOUNT))

        assert verification.db_alias == TENANT_ALIAS, "the owning database must be resolved from the signed event body"
        assert intake is not None and intake.payment_event is not None

        in_tenant = PaymentEvent.objects.using(TENANT_ALIAS).filter(provider="stripe", event_id=event_id).count()
        in_pool = PaymentEvent.objects.using("default").filter(provider="stripe", event_id=event_id).count()
        assert (in_tenant, in_pool) == (1, 0), (
            f"cross-tenant write: tenant_probe={in_tenant} default={in_pool} — "
            "a dedicated tenant's payment event must never land in the pool"
        )

    def test_the_event_is_attributed_to_the_tenants_workspace(
        self, stripe_webhook_settings, dedicated_tenant_stripe_method
    ):
        """Binding without attribution would still corrupt the ledger."""
        event_id = "evt_tenant_binding_attribution_001"

        _handle(_connect_request(event_id, TENANT_ACCOUNT))

        row = PaymentEvent.objects.using(TENANT_ALIAS).get(provider="stripe", event_id=event_id)
        assert str(row.workspace_id) == str(dedicated_tenant_stripe_method.workspace_id)
        assert row.provider_account_id == TENANT_ACCOUNT

    def test_a_replayed_delivery_stays_idempotent_inside_the_tenant_database(
        self, stripe_webhook_settings, dedicated_tenant_stripe_method
    ):
        """Idempotency has to hold on the tenant's connection, not the pool's.

        A ledger that dedupes in the wrong database is not a ledger.
        """
        event_id = "evt_tenant_binding_replay_001"

        _handle(_connect_request(event_id, TENANT_ACCOUNT))
        _, second = _handle(_connect_request(event_id, TENANT_ACCOUNT))

        assert second.duplicate is True
        assert second.processable is False
        assert PaymentEvent.objects.using(TENANT_ALIAS).filter(event_id=event_id).count() == 1
        assert PaymentEvent.objects.using("default").filter(event_id=event_id).count() == 0


class TestAnUnresolvableAccountIsNotSteeredAnywhere:
    def test_no_bind_happens_and_nothing_is_written_to_the_tenant(
        self, stripe_webhook_settings, dedicated_tenant_stripe_method
    ):
        """``None`` means "do not rebind" — never "pick a database".

        The event still records (an unclaimed connected account is exactly the
        kind of thing you want an audit row for), but it records where the
        request was already bound — the pool — and must not touch a tenant's
        database on a guess.
        """
        event_id = "evt_tenant_binding_unknown_account_001"

        verification, intake = _handle(_connect_request(event_id, UNKNOWN_ACCOUNT))

        assert verification.db_alias is None
        assert intake is not None
        assert PaymentEvent.objects.using(TENANT_ALIAS).filter(event_id=event_id).count() == 0
        assert PaymentEvent.objects.using("default").filter(event_id=event_id).count() == 1


class TestThePlatformEndpointIsUnchanged:
    def test_a_platform_event_resolves_no_alias_and_stays_in_the_pool(self, stripe_webhook_settings):
        """Platform (non-Connect) events carry no ``account``; nothing rebinds."""
        event = _make_event("evt_tenant_binding_platform_001", event_type="customer.subscription.created")
        payload = json.dumps(event).encode("utf-8")
        request = RequestFactory().post(
            "/workspaces/billing/stripe/webhook/",
            data=payload,
            content_type="application/json",
            **_stripe_signed_headers(payload, SECRET),
        )

        verification, intake = _handle(request, endpoint_name="team_subscriptions")

        assert verification.db_alias is None
        assert intake is not None and intake.payment_event is not None
        assert PaymentEvent.objects.using("default").filter(event_id="evt_tenant_binding_platform_001").count() == 1
        assert PaymentEvent.objects.using(TENANT_ALIAS).filter(event_id="evt_tenant_binding_platform_001").count() == 0

    def test_a_connect_event_delivered_to_the_platform_endpoint_records_nothing(
        self, stripe_webhook_settings, dedicated_tenant_stripe_method
    ):
        """The cross-delivery guard survives the move of the intake step.

        Recording it here would plant a row keyed by this ``event_id`` in the
        shared idempotency ledger, making the endpoint that legitimately owns
        the event dedupe-skip it forever.
        """
        event_id = "evt_tenant_binding_cross_delivery_001"

        verification, intake = _handle(_connect_request(event_id, TENANT_ACCOUNT), endpoint_name="team_subscriptions")

        assert verification.recordable is False
        assert intake is None
        assert PaymentEvent.objects.using("default").filter(event_id=event_id).count() == 0
        assert PaymentEvent.objects.using(TENANT_ALIAS).filter(event_id=event_id).count() == 0
