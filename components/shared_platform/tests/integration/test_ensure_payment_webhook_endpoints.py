"""ensure_payment_webhook_endpoints must never clobber provider-captured secrets.

The 2026-07-04 webhook-403 incident: rows whose signing_secret was captured
from Stripe at registration (the only copy — Stripe never returns it again)
were overwritten with the env-level secret by --update-existing, so every
delivery signed by those endpoints failed verification until Stripe disabled
the endpoint. The command now skips such rows (provider_endpoint_id set)
unless --force-secret is passed explicitly.
"""

from __future__ import annotations

from io import StringIO

import pytest
from django.apps import apps as django_apps
from django.core.management import call_command

URL = "https://api.example.test/sponsorship/donations/stripe/webhook/"


def _webhook_model():
    return django_apps.get_model("workspaces", "PaymentWebhookEndpoint")


@pytest.fixture
def method(workspace_factory):
    PaymentProvider = django_apps.get_model("workspaces", "PaymentProvider")
    PaymentMethod = django_apps.get_model("workspaces", "WorkspacePaymentMethod")
    provider, _ = PaymentProvider.objects.get_or_create(
        slug="stripe",
        defaults={
            "display_name": "Stripe",
            "provider_type": "api",
            "capabilities": ["donations"],
        },
    )
    return PaymentMethod.objects.create(
        workspace=workspace_factory(),
        provider=provider,
        display_name="Test Method",
        status="active",
        is_primary=True,
        enabled_contexts=["donations"],
        provider_account_id="acct_test_0001",
    )


def _run(**kwargs):
    out = StringIO()
    call_command(
        "ensure_payment_webhook_endpoints",
        name="donations",
        url=URL,
        stdout=out,
        **kwargs,
    )
    return out.getvalue()


@pytest.mark.integration
@pytest.mark.django_db
class TestEnsurePaymentWebhookEndpoints:
    def test_creates_missing_row_for_active_method(self, method):
        _run(secret="whsec_env_secret")
        row = _webhook_model().objects.get(method=method, name="donations")
        assert row.url == URL
        assert row.signing_secret == "whsec_env_secret"
        assert row.status == "active"

    def test_update_existing_syncs_env_managed_row(self, method):
        _webhook_model().objects.create(
            method=method,
            name="donations",
            url="https://old.example.test/hook/",
            signing_secret="whsec_stale",
        )
        _run(secret="whsec_env_secret", update_existing=True)
        row = _webhook_model().objects.get(method=method, name="donations")
        assert row.url == URL
        assert row.signing_secret == "whsec_env_secret"

    def test_update_existing_keeps_provider_captured_secret(self, method):
        _webhook_model().objects.create(
            method=method,
            name="donations",
            url=URL,
            signing_secret="whsec_captured_at_registration",
            provider_endpoint_id="we_test123",
        )
        output = _run(secret="whsec_env_secret", update_existing=True)
        row = _webhook_model().objects.get(method=method, name="donations")
        assert row.signing_secret == "whsec_captured_at_registration"
        assert row.provider_endpoint_id == "we_test123"
        assert "Skipping secret overwrite" in output
        assert "we_test123" in output

    def test_force_secret_overwrites_and_clears_endpoint_id(self, method):
        _webhook_model().objects.create(
            method=method,
            name="donations",
            url=URL,
            signing_secret="whsec_captured_at_registration",
            provider_endpoint_id="we_test123",
        )
        _run(secret="whsec_env_secret", update_existing=True, force_secret=True)
        row = _webhook_model().objects.get(method=method, name="donations")
        assert row.signing_secret == "whsec_env_secret"
        # The captured secret is gone, so the row is env-managed now.
        assert row.provider_endpoint_id == ""

    def test_dry_run_writes_nothing(self, method):
        _webhook_model().objects.create(
            method=method,
            name="donations",
            url="https://old.example.test/hook/",
            signing_secret="whsec_stale",
        )
        _run(secret="whsec_env_secret", update_existing=True, dry_run=True)
        row = _webhook_model().objects.get(method=method, name="donations")
        assert row.signing_secret == "whsec_stale"
        assert row.url == "https://old.example.test/hook/"
