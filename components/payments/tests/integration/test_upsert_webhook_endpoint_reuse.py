"""Auto-registering a webhook must reuse an existing provider endpoint.

Stripe delivers every subscribed event on a URL to EVERY endpoint registered
for that URL, each signed with that endpoint's own secret. Historically each
workspace onboarding created another Stripe endpoint for the same global
donations URL — duplicate deliveries, and once one row's captured secret was
overwritten (see test_ensure_payment_webhook_endpoints), that endpoint 403'd
every delivery until Stripe disabled it (2026-07-04 incident).

The upsert_webhook action now reuses a sibling method's registration
(same url + name + connect-mode) instead of creating another provider-side
endpoint, and records the provider endpoint id alongside the captured secret.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from django.apps import apps as django_apps
from rest_framework.test import APIRequestFactory, force_authenticate

from components.payments.api.urls import payment_method_upsert_webhook

URL = "https://api.example.test/sponsorship/donations/stripe/webhook/"


def _webhook_model():
    return django_apps.get_model("workspaces", "PaymentWebhookEndpoint")


class _FakeGateway:
    def __init__(self):
        self.register_calls = []
        self._counter = 0

    def register_webhook_endpoint(self, **kwargs):
        self.register_calls.append(kwargs)
        self._counter += 1
        return {
            "secret": f"whsec_captured_{self._counter}",
            "id": f"we_test_{self._counter}",
        }


class _FakeGatewayProvider:
    def __init__(self, gateway):
        self._gateway = gateway

    def get_gateway_for_provider(self, slug):
        return self._gateway


@pytest.fixture
def staff_user(user_factory):
    user = user_factory()
    user.is_staff = True
    user.save(update_fields=["is_staff"])
    return user


@pytest.fixture
def fake_gateway():
    gateway = _FakeGateway()
    with patch(
        "components.payments.application.providers.payment_gateway_provider.make_payment_gateway_provider",
        return_value=_FakeGatewayProvider(gateway),
    ):
        yield gateway


def _post_webhook(user, workspace, method, payload):
    request = APIRequestFactory().post(
        f"/workspaces/{workspace.id}/payments/methods/{method.id}/webhooks/",
        payload,
        format="json",
    )
    force_authenticate(request, user=user)
    return payment_method_upsert_webhook(request, workspace_id=str(workspace.id), id=str(method.id))


@pytest.mark.integration
@pytest.mark.django_db
class TestUpsertWebhookEndpointReuse:
    def test_first_auto_register_creates_and_records_endpoint_id(
        self, settings, staff_user, workspace_factory, payment_method_factory, fake_gateway
    ):
        settings.STRIPE_SECRET_KEY = "sk_test_dummy"
        workspace = workspace_factory()
        method = payment_method_factory(workspace)

        response = _post_webhook(
            staff_user,
            workspace,
            method,
            {"name": "donations", "url": URL, "auto_register": True},
        )

        assert response.status_code == 201, response.data
        assert len(fake_gateway.register_calls) == 1
        row = _webhook_model().objects.get(method=method, name="donations")
        assert row.signing_secret == "whsec_captured_1"
        assert row.provider_endpoint_id == "we_test_1"

    def test_second_connect_method_reuses_existing_endpoint(
        self, settings, staff_user, workspace_factory, payment_method_factory, fake_gateway
    ):
        settings.STRIPE_SECRET_KEY = "sk_test_dummy"
        first_ws = workspace_factory()
        first_method = payment_method_factory(first_ws)
        _post_webhook(
            staff_user,
            first_ws,
            first_method,
            {"name": "donations", "url": URL, "auto_register": True},
        )

        second_ws = workspace_factory()
        second_method = payment_method_factory(second_ws)
        response = _post_webhook(
            staff_user,
            second_ws,
            second_method,
            {"name": "donations", "url": URL, "auto_register": True},
        )

        assert response.status_code == 201, response.data
        # No second provider-side endpoint was created.
        assert len(fake_gateway.register_calls) == 1
        row = _webhook_model().objects.get(method=second_method, name="donations")
        assert row.signing_secret == "whsec_captured_1"
        assert row.provider_endpoint_id == "we_test_1"

    def test_platform_method_does_not_reuse_connect_endpoint(
        self, settings, staff_user, workspace_factory, payment_method_factory, fake_gateway
    ):
        settings.STRIPE_SECRET_KEY = "sk_test_dummy"
        connect_ws = workspace_factory()
        connect_method = payment_method_factory(connect_ws)  # has provider_account_id
        _post_webhook(
            staff_user,
            connect_ws,
            connect_method,
            {"name": "donations", "url": URL, "auto_register": True},
        )

        platform_ws = workspace_factory()
        platform_method = payment_method_factory(platform_ws)
        # Factory always sets a non-empty account id; force platform mode.
        platform_method.provider_account_id = ""
        platform_method.save(update_fields=["provider_account_id"])

        response = _post_webhook(
            staff_user,
            platform_ws,
            platform_method,
            {"name": "donations", "url": URL, "auto_register": True},
        )

        assert response.status_code == 201, response.data
        # Connect-mode endpoint must not serve a platform-mode method:
        # a second (platform) endpoint is registered with the provider.
        assert len(fake_gateway.register_calls) == 2
        assert fake_gateway.register_calls[1]["connect"] is False
        row = _webhook_model().objects.get(method=platform_method, name="donations")
        assert row.signing_secret == "whsec_captured_2"
        assert row.provider_endpoint_id == "we_test_2"

    def test_manual_secret_paste_still_works(
        self, settings, staff_user, workspace_factory, payment_method_factory, fake_gateway
    ):
        settings.STRIPE_SECRET_KEY = "sk_test_dummy"
        workspace = workspace_factory()
        method = payment_method_factory(workspace)

        response = _post_webhook(
            staff_user,
            workspace,
            method,
            {"name": "donations", "url": URL, "signing_secret": "whsec_pasted"},
        )

        assert response.status_code == 201, response.data
        assert fake_gateway.register_calls == []
        row = _webhook_model().objects.get(method=method, name="donations")
        assert row.signing_secret == "whsec_pasted"
        assert row.provider_endpoint_id == ""
