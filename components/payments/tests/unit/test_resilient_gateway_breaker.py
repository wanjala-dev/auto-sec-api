"""Tests for ResilientGateway circuit-breaker discrimination.

The breaker must distinguish a per-request CLIENT/CONFIG error (a revoked
connected account, a declined card, a bad-params request — all surfaced as
``ValidationError``-based payment domain errors by the Stripe adapter) from a
genuine provider-availability failure (rate limit, connection error — surfaced
as ``IntegrationError``-based errors, or any unexpected non-domain Exception).

Recording a client/config error as a provider failure would open the breaker
and reject EVERY org's checkout, turning one org's misconfiguration into a
platform-wide outage. So:

- ValidationError-based (and other client-error taxonomy) → record_success,
  breaker stays CLOSED.
- IntegrationError-based / generic Exception → record_failure.
"""
from __future__ import annotations

import pytest

from components.payments.domain.errors import (
    PaymentAccountUnavailableError,
    PaymentValidationError,
    ProviderUnavailableError,
)
from components.payments.infrastructure.gateways.resilient_gateway import ResilientGateway
from components.shared_kernel.domain.circuit_breaker import (
    CircuitBreakerConfig,
    CircuitState,
    ProviderCircuitBreaker,
    circuit_breaker_registry,
)


class _FakeInner:
    """Inner gateway whose create_checkout_session raises a chosen error."""

    def __init__(self, raising_exc):
        self._exc = raising_exc

    def create_checkout_session(self, method, plan, **kwargs):
        raise self._exc

    def ensure_plan_resources(self, method, plan):
        raise self._exc


def _gateway_with_fresh_breaker(slug, inner):
    """Wire a ResilientGateway onto a fresh, isolated breaker.

    Uses a low failure_threshold so a single recorded failure opens the
    breaker — makes the "did we record a failure?" assertion crisp.
    """
    gw = ResilientGateway(slug, inner)
    breaker = ProviderCircuitBreaker(slug, CircuitBreakerConfig(failure_threshold=1))
    gw._breaker = breaker
    return gw, breaker


@pytest.mark.parametrize(
    "client_exc",
    [
        PaymentAccountUnavailableError("org can't accept payments right now"),
        PaymentValidationError("Your card was declined."),
    ],
)
def test_client_error_does_not_open_breaker(client_exc):
    gw, breaker = _gateway_with_fresh_breaker("stripe-client", _FakeInner(client_exc))

    with pytest.raises(type(client_exc)):
        gw.create_checkout_session(object(), None)

    snapshot = breaker.health_snapshot()
    assert breaker.state is CircuitState.CLOSED
    # No failure recorded — a successful round-trip was recorded instead.
    assert snapshot.failure_count == 0
    assert snapshot.success_count == 1


def test_provider_availability_error_opens_breaker():
    exc = ProviderUnavailableError("stripe")
    gw, breaker = _gateway_with_fresh_breaker("stripe-prov", _FakeInner(exc))

    with pytest.raises(ProviderUnavailableError):
        gw.create_checkout_session(object(), None)

    snapshot = breaker.health_snapshot()
    # IntegrationError-based → recorded as a provider failure → breaker OPEN
    # (failure_threshold=1).
    assert snapshot.failure_count == 1
    assert breaker.state is CircuitState.OPEN


def test_unexpected_exception_opens_breaker():
    exc = RuntimeError("totally unexpected")
    gw, breaker = _gateway_with_fresh_breaker("stripe-unexpected", _FakeInner(exc))

    with pytest.raises(RuntimeError):
        gw.create_checkout_session(object(), None)

    assert breaker.health_snapshot().failure_count == 1
    assert breaker.state is CircuitState.OPEN


def test_ensure_plan_resources_client_error_does_not_open_breaker():
    exc = PaymentValidationError("bad plan")
    gw, breaker = _gateway_with_fresh_breaker("stripe-plan", _FakeInner(exc))

    with pytest.raises(PaymentValidationError):
        gw.ensure_plan_resources(object(), None)

    assert breaker.health_snapshot().failure_count == 0
    assert breaker.state is CircuitState.CLOSED


def test_success_records_success():
    class _OkInner:
        def create_checkout_session(self, method, plan, **kwargs):
            return {"sessionId": "cs_test_ok"}

    gw, breaker = _gateway_with_fresh_breaker("stripe-ok", _OkInner())
    result = gw.create_checkout_session(object(), None)

    assert result == {"sessionId": "cs_test_ok"}
    assert breaker.health_snapshot().success_count == 1
    assert breaker.state is CircuitState.CLOSED


def teardown_module(module):
    # Keep the process-global registry clean for other test modules.
    circuit_breaker_registry.reset_all()
