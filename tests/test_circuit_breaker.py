"""Tests for the payment provider circuit breaker and fallback routing.

These are pure-Python unit tests with no Django dependency — they test
the domain logic and gateway wrappers in isolation.
"""

from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from components.shared_kernel.domain.circuit_breaker import (
    CircuitBreakerConfig,
    CircuitBreakerRegistry,
    CircuitState,
    ProviderCircuitBreaker,
    circuit_breaker_registry,
)
from components.payments.domain.errors import (
    AllProvidersUnavailableError,
    ProviderUnavailableError,
)
from components.payments.infrastructure.gateways.resilient_gateway import (
    ResilientGateway,
)


# ── Helpers ──────────────────────────────────────────────────────────


def _fast_config(**overrides) -> CircuitBreakerConfig:
    """Config with very short timeouts for testing."""
    defaults = dict(
        failure_threshold=3,
        success_threshold=2,
        recovery_timeout=0.1,  # 100ms
        window_size=5.0,
        half_open_max_calls=2,
    )
    defaults.update(overrides)
    return CircuitBreakerConfig(**defaults)


# ── ProviderCircuitBreaker ───────────────────────────────────────────


class TestProviderCircuitBreaker:
    def test_starts_closed(self):
        cb = ProviderCircuitBreaker("stripe", _fast_config())
        assert cb.state is CircuitState.CLOSED

    def test_stays_closed_below_threshold(self):
        cb = ProviderCircuitBreaker("stripe", _fast_config(failure_threshold=3))
        cb.record_failure()
        cb.record_failure()
        assert cb.state is CircuitState.CLOSED
        assert cb.allow_request() is True

    def test_opens_at_threshold(self):
        cb = ProviderCircuitBreaker("stripe", _fast_config(failure_threshold=3))
        for _ in range(3):
            cb.record_failure()
        assert cb.state is CircuitState.OPEN
        assert cb.allow_request() is False

    def test_transitions_to_half_open_after_recovery(self):
        cb = ProviderCircuitBreaker("stripe", _fast_config(
            failure_threshold=2, recovery_timeout=0.05,
        ))
        cb.record_failure()
        cb.record_failure()
        assert cb.state is CircuitState.OPEN
        time.sleep(0.06)
        assert cb.state is CircuitState.HALF_OPEN

    def test_half_open_allows_limited_calls(self):
        cb = ProviderCircuitBreaker("stripe", _fast_config(
            failure_threshold=2, recovery_timeout=0.05, half_open_max_calls=2,
        ))
        cb.record_failure()
        cb.record_failure()
        time.sleep(0.06)
        assert cb.allow_request() is True
        assert cb.allow_request() is True
        assert cb.allow_request() is False  # exceeds limit

    def test_half_open_closes_on_success_threshold(self):
        cb = ProviderCircuitBreaker("stripe", _fast_config(
            failure_threshold=2, recovery_timeout=0.05, success_threshold=2,
        ))
        cb.record_failure()
        cb.record_failure()
        time.sleep(0.06)
        cb.allow_request()
        cb.record_success()
        cb.allow_request()
        cb.record_success()
        assert cb.state is CircuitState.CLOSED

    def test_half_open_reopens_on_failure(self):
        cb = ProviderCircuitBreaker("stripe", _fast_config(
            failure_threshold=2, recovery_timeout=0.05,
        ))
        cb.record_failure()
        cb.record_failure()
        time.sleep(0.06)
        cb.allow_request()
        cb.record_failure()
        assert cb.state is CircuitState.OPEN

    def test_successes_keep_closed(self):
        cb = ProviderCircuitBreaker("stripe", _fast_config(failure_threshold=3))
        for _ in range(10):
            cb.record_success()
        assert cb.state is CircuitState.CLOSED

    def test_mixed_below_threshold_stays_closed(self):
        cb = ProviderCircuitBreaker("stripe", _fast_config(failure_threshold=5))
        cb.record_failure()
        cb.record_success()
        cb.record_failure()
        cb.record_success()
        assert cb.state is CircuitState.CLOSED

    def test_reset_forces_closed(self):
        cb = ProviderCircuitBreaker("stripe", _fast_config(failure_threshold=2))
        cb.record_failure()
        cb.record_failure()
        assert cb.state is CircuitState.OPEN
        cb.reset()
        assert cb.state is CircuitState.CLOSED
        assert cb.allow_request() is True

    def test_health_snapshot(self):
        cb = ProviderCircuitBreaker("stripe", _fast_config(failure_threshold=5))
        cb.record_success()
        cb.record_success()
        cb.record_failure()
        snap = cb.health_snapshot()
        assert snap.slug == "stripe"
        assert snap.state is CircuitState.CLOSED
        assert snap.success_count == 2
        assert snap.failure_count == 1
        assert 0.3 < snap.failure_rate < 0.4

    def test_window_prunes_old_outcomes(self):
        cb = ProviderCircuitBreaker("stripe", _fast_config(
            failure_threshold=3, window_size=0.05,
        ))
        cb.record_failure()
        cb.record_failure()
        time.sleep(0.06)
        # Old failures should be pruned; this third failure is the only one
        # in the window, so we stay CLOSED.
        cb.record_failure()
        assert cb.state is CircuitState.CLOSED


class TestCircuitBreakerThreadSafety:
    def test_concurrent_failures_open_circuit(self):
        cb = ProviderCircuitBreaker("stripe", _fast_config(failure_threshold=5))
        barrier = threading.Barrier(10)

        def fail():
            barrier.wait()
            cb.record_failure()

        threads = [threading.Thread(target=fail) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert cb.state is CircuitState.OPEN


# ── CircuitBreakerRegistry ───────────────────────────────────────────


class TestCircuitBreakerRegistry:
    def test_get_creates_on_first_access(self):
        reg = CircuitBreakerRegistry()
        breaker = reg.get("stripe")
        assert breaker.slug == "stripe"
        assert breaker is reg.get("stripe")

    def test_case_insensitive(self):
        reg = CircuitBreakerRegistry()
        assert reg.get("Stripe") is reg.get("stripe")

    def test_configure_replaces_breaker(self):
        reg = CircuitBreakerRegistry()
        old = reg.get("stripe")
        custom = CircuitBreakerConfig(failure_threshold=10)
        reg.configure("stripe", custom)
        new = reg.get("stripe")
        assert new is not old
        assert new.config.failure_threshold == 10

    def test_all_snapshots(self):
        reg = CircuitBreakerRegistry()
        reg.get("stripe")
        reg.get("braintree")
        snaps = reg.all_snapshots()
        slugs = {s.slug for s in snaps}
        assert slugs == {"stripe", "braintree"}

    def test_reset_all(self):
        reg = CircuitBreakerRegistry(_fast_config(failure_threshold=2))
        for slug in ("stripe", "braintree"):
            b = reg.get(slug)
            b.record_failure()
            b.record_failure()
            assert b.state is CircuitState.OPEN
        reg.reset_all()
        for slug in ("stripe", "braintree"):
            assert reg.get(slug).state is CircuitState.CLOSED


# ── ResilientGateway ─────────────────────────────────────────────────


class TestResilientGateway:
    def setup_method(self):
        circuit_breaker_registry.reset_all()

    def test_records_success(self):
        inner = MagicMock()
        inner.create_checkout_session.return_value = {"id": "cs_123"}
        gw = ResilientGateway("stripe", inner)
        result = gw.create_checkout_session("method", "plan", currency="usd")
        assert result == {"id": "cs_123"}
        snap = circuit_breaker_registry.get("stripe").health_snapshot()
        assert snap.success_count == 1

    def test_records_failure(self):
        inner = MagicMock()
        inner.create_checkout_session.side_effect = RuntimeError("Stripe down")
        gw = ResilientGateway("stripe", inner)
        with pytest.raises(RuntimeError):
            gw.create_checkout_session("method", "plan")
        snap = circuit_breaker_registry.get("stripe").health_snapshot()
        assert snap.failure_count == 1

    def test_delegates_verify_webhook_without_tracking(self):
        inner = MagicMock()
        inner.verify_webhook.return_value = "verified"
        gw = ResilientGateway("stripe", inner)
        assert gw.verify_webhook(request="r") == "verified"
        snap = circuit_breaker_registry.get("stripe").health_snapshot()
        assert snap.success_count == 0
        assert snap.failure_count == 0

    def test_getattr_delegates(self):
        inner = MagicMock()
        inner.slug = "stripe"
        gw = ResilientGateway("stripe", inner)
        assert gw.slug == "stripe"

    def test_ensure_plan_resources_tracked(self):
        inner = MagicMock()
        gw = ResilientGateway("stripe", inner)
        gw.ensure_plan_resources("method", "plan")
        snap = circuit_breaker_registry.get("stripe").health_snapshot()
        assert snap.success_count == 1


# ── PaymentGatewayProvider with fallback ─────────────────────────────


class TestPaymentGatewayProviderFallback:
    def setup_method(self):
        circuit_breaker_registry.reset_all()

    def _make_provider(self):
        from components.payments.application.providers.payment_gateway_provider import (
            PaymentGatewayProvider,
        )

        gateways = {
            "stripe": MagicMock(slug="stripe"),
            "braintree": MagicMock(slug="braintree"),
            "bitpay": MagicMock(slug="bitpay"),
        }
        return PaymentGatewayProvider(gateways=gateways), gateways

    def test_get_healthy_gateway_when_closed(self):
        provider, gateways = self._make_provider()
        gw = provider.get_healthy_gateway("stripe")
        assert gw is gateways["stripe"]

    def test_get_healthy_gateway_when_open(self):
        provider, _ = self._make_provider()
        breaker = circuit_breaker_registry.get("stripe")
        breaker._state = CircuitState.OPEN
        breaker._opened_at = time.monotonic()  # recently opened
        with pytest.raises(ProviderUnavailableError):
            provider.get_healthy_gateway("stripe")

    def test_fallback_returns_preferred_when_healthy(self):
        provider, gateways = self._make_provider()
        slug, gw = provider.get_gateway_with_fallback("stripe")
        assert slug == "stripe"
        assert gw is gateways["stripe"]

    def test_fallback_skips_open_provider(self):
        provider, gateways = self._make_provider()
        # Open Stripe's breaker
        breaker = circuit_breaker_registry.get("stripe")
        breaker._state = CircuitState.OPEN
        breaker._opened_at = time.monotonic()
        slug, gw = provider.get_gateway_with_fallback("stripe")
        assert slug != "stripe"
        assert slug in ("braintree", "bitpay")

    def test_fallback_raises_when_all_open(self):
        provider, _ = self._make_provider()
        for s in ("stripe", "braintree", "bitpay"):
            breaker = circuit_breaker_registry.get(s)
            breaker._state = CircuitState.OPEN
            breaker._opened_at = time.monotonic()
        with pytest.raises(AllProvidersUnavailableError) as exc_info:
            provider.get_gateway_with_fallback("stripe")
        assert "stripe" in exc_info.value.attempted_slugs

    def test_fallback_prefers_healthier_provider(self):
        provider, gateways = self._make_provider()
        # Open Stripe
        breaker_s = circuit_breaker_registry.get("stripe")
        breaker_s._state = CircuitState.OPEN
        breaker_s._opened_at = time.monotonic()
        # Braintree has some failures but CLOSED
        breaker_bt = circuit_breaker_registry.get("braintree")
        breaker_bt.record_failure()
        breaker_bt.record_failure()
        # BitPay is pristine
        slug, gw = provider.get_gateway_with_fallback("stripe")
        assert slug == "bitpay"

    def test_provider_health_returns_all_snapshots(self):
        provider, _ = self._make_provider()
        snaps = provider.provider_health()
        slugs = {s.slug for s in snaps}
        assert slugs == {"stripe", "braintree", "bitpay"}

    def test_eligible_slugs_filters_candidates(self):
        provider, gateways = self._make_provider()
        breaker_s = circuit_breaker_registry.get("stripe")
        breaker_s._state = CircuitState.OPEN
        breaker_s._opened_at = time.monotonic()
        # Only allow braintree as fallback
        slug, gw = provider.get_gateway_with_fallback(
            "stripe", eligible_slugs=["braintree"],
        )
        assert slug == "braintree"
