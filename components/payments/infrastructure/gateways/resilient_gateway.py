"""Resilient gateway wrapper that integrates circuit-breaker health tracking.

Wraps any ``PaymentGatewayPort``-compatible gateway so that every call to
``create_checkout_session`` or ``capture_payment`` automatically records
success/failure with the circuit breaker registry.  Webhook verification
is *not* wrapped because it's an inbound operation (the provider is
calling us, not the other way around).

Usage::

    from components.payments.infrastructure.gateways.resilient_gateway import ResilientGateway

    stripe_gw = ResilientGateway("stripe", StripeGatewayAdapter())
    # Use stripe_gw wherever you'd use StripeGatewayAdapter — the
    # circuit breaker recording happens transparently.
"""

from __future__ import annotations

import logging
from typing import Any

from components.shared_kernel.domain.circuit_breaker import circuit_breaker_registry
from components.shared_kernel.domain.errors import (
    AuthorizationError,
    ConflictError,
    NotFoundError,
    ValidationError,
)

logger = logging.getLogger(__name__)

# Domain-error taxonomy that represents a per-request CLIENT / CONFIG problem,
# NOT a provider-availability failure. These must NOT trip the circuit breaker:
# a revoked connected account, a declined card, or a bad-params request is
# scoped to one org / one checkout. Recording them as provider failures would
# open the breaker and reject EVERY org's checkout — turning a single org's
# misconfiguration into a platform-wide outage. Provider-availability problems
# (rate limit, connection/API errors) are mapped to IntegrationError-based
# domain errors by the adapter and fall through to the `except Exception` arm,
# which DOES record a failure.
_CLIENT_ERRORS = (ValidationError, NotFoundError, ConflictError, AuthorizationError)


class ResilientGateway:
    """Transparent wrapper that records outcomes with the circuit breaker."""

    def __init__(self, slug: str, inner):
        self.slug = slug
        self._inner = inner
        self._breaker = circuit_breaker_registry.get(slug)

    # -- Delegated, instrumented methods ------------------------------------

    def create_checkout_session(self, method, plan, **kwargs) -> Any:
        try:
            result = self._inner.create_checkout_session(method, plan, **kwargs)
            self._breaker.record_success()
            return result
        except _CLIENT_ERRORS:
            # Client/config error — the provider responded, it's just that this
            # one request can't proceed. Treat as a successful round-trip for
            # health purposes so it does not open the breaker for other orgs.
            self._breaker.record_success()
            raise
        except Exception:
            self._breaker.record_failure()
            raise

    def ensure_plan_resources(self, method, plan) -> None:
        try:
            self._inner.ensure_plan_resources(method, plan)
            self._breaker.record_success()
        except _CLIENT_ERRORS:
            # See create_checkout_session — a per-request client/config error
            # must not be recorded as a provider-availability failure.
            self._breaker.record_success()
            raise
        except Exception:
            self._breaker.record_failure()
            raise

    # -- Pass-through methods (not health-tracked) --------------------------

    def verify_webhook(self, *args, **kwargs):
        """Webhook verification is inbound — no circuit breaker needed."""
        return self._inner.verify_webhook(*args, **kwargs)

    def __getattr__(self, name: str):
        """Delegate everything else to the inner gateway."""
        return getattr(self._inner, name)
