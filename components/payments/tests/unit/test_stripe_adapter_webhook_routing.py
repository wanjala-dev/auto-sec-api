"""Regression tests for Stripe webhook routing by event.account.

Pre-fix bug: when multiple ``WorkspacePaymentMethod`` rows shared a
Connect webhook signing secret (which is the normal case for a single
platform-level Connect endpoint), the verifier returned the first
method whose secret matched the signature. That method's
``provider_account_id`` could differ from ``event.account`` in the
payload, causing every downstream Stripe API call to be issued against
the wrong connected account and 404 with ``No such checkout session``.
PaymentEvents got attributed to the wrong workspace; donations on the
originating workspace stayed stuck in ``processing``.

Fix: after signature verification (in either the global-secret path or
the per-method-webhook-secret path), the gateway re-resolves the method
by ``event.account`` and only falls back to the verifying method's
account for non-Connect platform events (where ``event.account`` is
absent).

These tests exercise the gateway directly with fakes — no DB needed.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

from django.test import override_settings

from components.payments.infrastructure.adapters.stripe_adapter import (
    StripePaymentAdapter,
)
from components.payments.tests._helpers.stripe_webhook_signing import (
    make_event as _make_event,
    stripe_signed_headers as _stripe_signed_headers,
)


class _FakeWebhookList:
    """Minimal stand-in for ``method.webhooks`` (the reverse FK manager)."""

    def __init__(self, webhooks):
        self._webhooks = webhooks

    def filter(self, **kwargs):
        results = []
        for w in self._webhooks:
            if "status" in kwargs and getattr(w, "status", None) != kwargs["status"]:
                continue
            if "name" in kwargs and getattr(w, "name", None) != kwargs["name"]:
                continue
            results.append(w)
        return _FakeWebhookList(results)

    def __iter__(self):
        return iter(self._webhooks)


class _FakeMethodsQuerySet:
    """Minimal stand-in for the ``WorkspacePaymentMethod`` queryset.

    Only implements the surface the gateway uses: ``select_related``,
    ``filter`` (by ``provider_account_id``), ``distinct``, iteration.
    Other filters (``webhooks__status``, ``webhooks__signing_secret``)
    are accepted but ignored — the test fixtures already encode the
    desired candidate set.
    """

    def __init__(self, methods):
        self._methods = list(methods)

    def select_related(self, *args, **kwargs):
        return self

    def distinct(self):
        return self

    def filter(self, **kwargs):
        account = kwargs.get("provider_account_id")
        if account is not None:
            return _FakeMethodsQuerySet(
                m for m in self._methods if m.provider_account_id == account
            )
        return self

    def first(self):
        return self._methods[0] if self._methods else None

    def __iter__(self):
        return iter(self._methods)


def _build_method(*, account: str, secret: str, workspace_id: str = "ws-default"):
    webhook = SimpleNamespace(
        signing_secret=secret,
        status="active",
        name="donations",
    )
    return SimpleNamespace(
        provider_account_id=account,
        provider=SimpleNamespace(slug="stripe"),
        workspace=SimpleNamespace(id=workspace_id),
        workspace_id=workspace_id,
        webhooks=_FakeWebhookList([webhook]),
        # read_payment_method_credentials decrypts this; "" returns {}
        encrypted_credentials="",
    )


def _build_request(payload_bytes: bytes, secret: str):
    headers = _stripe_signed_headers(payload_bytes, secret)
    return SimpleNamespace(
        body=payload_bytes,
        META={"HTTP_STRIPE_SIGNATURE": headers["HTTP_STRIPE_SIGNATURE"]},
        GET={},
    )


def _connect_event_payload(event_id: str, account: str) -> bytes:
    event = _make_event(event_id)
    event["account"] = account
    return json.dumps(event).encode("utf-8")


def _platform_event_payload(event_id: str) -> bytes:
    # No "account" key → platform-level event, not Connect
    event = _make_event(event_id)
    return json.dumps(event).encode("utf-8")


@override_settings(
    STRIPE_WEBHOOK_KEY="",
    STRIPE_CONNECT_WEBHOOK_SECRET="",
    STRIPE_CONNECT_DONATIONS_WEBHOOK_SECRET="",
    STRIPE_SECRET_KEY="sk_test_for_unit_tests",
)
def test_per_method_path_routes_by_event_account_when_secret_is_shared():
    """Two methods share a signing secret. Connect event names one
    of them via event.account. Verifier MUST return that method —
    not whichever was iterated first.
    """
    secret = "whsec_shared_connect_secret_xxx"
    target_account = "acct_target_xxx"
    absorbing_account = "acct_absorbing_xxx"

    payload = _connect_event_payload("evt_routing_001", target_account)

    absorbing_method = _build_method(account=absorbing_account, secret=secret)
    target_method = _build_method(account=target_account, secret=secret)
    candidate_methods = _FakeMethodsQuerySet([absorbing_method, target_method])

    request = _build_request(payload, secret)
    result = StripePaymentAdapter().verify_webhook(
        request, "donations", candidate_methods
    )

    assert result.account_id == target_account
    assert result.method is target_method
    assert result.workspace is target_method.workspace


@override_settings(
    STRIPE_WEBHOOK_KEY="",
    STRIPE_CONNECT_WEBHOOK_SECRET="",
    STRIPE_CONNECT_DONATIONS_WEBHOOK_SECRET="",
    STRIPE_SECRET_KEY="sk_test_for_unit_tests",
)
def test_per_method_path_returns_event_account_when_no_method_matches():
    """Connect event from an unknown account: account_id flows through
    so downstream API calls hit the right stripe_account, but
    method/workspace are None to avoid attributing to the wrong
    workspace.
    """
    secret = "whsec_shared_connect_secret_yyy"
    absorbing_account = "acct_absorbing_yyy"
    unknown_account = "acct_unknown_yyy"

    payload = _connect_event_payload("evt_routing_002", unknown_account)

    absorbing_method = _build_method(account=absorbing_account, secret=secret)
    candidate_methods = _FakeMethodsQuerySet([absorbing_method])

    request = _build_request(payload, secret)
    result = StripePaymentAdapter().verify_webhook(
        request, "donations", candidate_methods
    )

    assert result.account_id == unknown_account
    assert result.method is None
    assert result.workspace is None


@override_settings(
    STRIPE_WEBHOOK_KEY="",
    STRIPE_CONNECT_WEBHOOK_SECRET="",
    STRIPE_CONNECT_DONATIONS_WEBHOOK_SECRET="",
    STRIPE_SECRET_KEY="sk_test_for_unit_tests",
)
def test_per_method_path_keeps_method_account_for_platform_events():
    """Platform events have no event.account — the verifying method's
    account stays as account_id (this is the non-Connect path,
    e.g. team-plan billing).
    """
    secret = "whsec_platform_zzz"
    method_account = "acct_platform_zzz"

    payload = _platform_event_payload("evt_platform_001")

    method = _build_method(account=method_account, secret=secret)
    candidate_methods = _FakeMethodsQuerySet([method])

    request = _build_request(payload, secret)
    result = StripePaymentAdapter().verify_webhook(
        request, "donations", candidate_methods
    )

    assert result.account_id == method_account
    assert result.method is method


@override_settings(
    STRIPE_WEBHOOK_KEY="whsec_global_aaa",
    STRIPE_CONNECT_WEBHOOK_SECRET="",
    STRIPE_CONNECT_DONATIONS_WEBHOOK_SECRET="",
    STRIPE_SECRET_KEY="sk_test_for_unit_tests",
)
def test_global_secret_path_uses_event_account_for_method_lookup():
    """Even with a single global signing secret, the gateway must use
    event.account (not the request header) to find the correct method.
    """
    target_account = "acct_global_target"
    other_account = "acct_global_other"

    payload = _connect_event_payload("evt_global_001", target_account)

    target_method = _build_method(
        account=target_account, secret="ignored", workspace_id="ws-target"
    )
    other_method = _build_method(
        account=other_account, secret="ignored", workspace_id="ws-other"
    )
    candidate_methods = _FakeMethodsQuerySet([other_method, target_method])

    request = _build_request(payload, "whsec_global_aaa")
    result = StripePaymentAdapter().verify_webhook(
        request, "donations", candidate_methods
    )

    assert result.account_id == target_account
    assert result.method is target_method
    assert result.workspace is target_method.workspace
