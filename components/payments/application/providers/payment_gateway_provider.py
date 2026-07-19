from __future__ import annotations

import logging
from collections.abc import Mapping

from components.shared_kernel.domain.circuit_breaker import (
    CircuitState,
    HealthSnapshot,
    circuit_breaker_registry,
)
from components.payments.domain.errors import (
    AllProvidersUnavailableError,
    ProviderUnavailableError,
    UnsupportedPaymentProviderError,
)
from components.payments.application.ports.payment_gateway_port import PaymentGatewayPort
from components.payments.application.ports.payment_gateway_provider_port import (
    PaymentGatewayProviderPort,
)

logger = logging.getLogger(__name__)

PaymentGatewayAdapters = dict[str, PaymentGatewayPort]


class PaymentGatewayProvider(PaymentGatewayProviderPort):
    """Application-level provider that wires the correct payment gateway adapter by vendor slug.

    Integrates with the circuit breaker registry to:
    * Reject requests to providers whose breakers are OPEN.
    * Provide fallback ordering when multiple providers support the same context.
    """

    def __init__(self, gateways: Mapping[str, PaymentGatewayPort] | None = None):
        self._gateways: PaymentGatewayAdapters = dict(gateways or self._default_gateways())

    @staticmethod
    def _default_gateways() -> PaymentGatewayAdapters:
        from components.payments.infrastructure.gateways.bitpay_gateway import (
            BitpayGatewayAdapter,
        )
        from components.payments.infrastructure.gateways.resilient_gateway import (
            ResilientGateway,
        )
        from components.payments.infrastructure.gateways.stripe_gateway import (
            StripeGatewayAdapter,
        )

        gateways: PaymentGatewayAdapters = {
            "stripe": ResilientGateway("stripe", StripeGatewayAdapter()),
            "bitpay": ResilientGateway("bitpay", BitpayGatewayAdapter()),
        }
        # Braintree is gated behind the `payments.braintree` FeatureFlag. It
        # ships disabled for launch — the marketplace / sub-merchant onboarding
        # flow needs to land before workspaces can safely use it. Flip the
        # flag on (per workspace or globally) once that's built.
        if _is_braintree_enabled():
            try:
                from components.payments.infrastructure.gateways.braintree_gateway import (
                    BraintreeGatewayAdapter,
                )
            except Exception:  # pragma: no cover - optional dependency path
                BraintreeGatewayAdapter = None  # type: ignore
            if BraintreeGatewayAdapter is not None:
                try:
                    gateways["braintree"] = ResilientGateway("braintree", BraintreeGatewayAdapter())
                except Exception:  # pragma: no cover - optional dependency path
                    pass
        return gateways

    @staticmethod
    def _normalize_slug(slug: str) -> str:
        slug_key = slug.lower()
        return slug_key.split("-", 1)[0].split("_", 1)[0]

    # -----------------------------------------------------------------
    # Core lookup (unchanged contract)
    # -----------------------------------------------------------------

    def get_gateway_for_provider(self, provider_slug: str) -> PaymentGatewayPort:
        normalized_slug = self._normalize_slug(provider_slug)
        gateway = self._gateways.get(provider_slug.lower()) or self._gateways.get(normalized_slug)
        if gateway is None:
            raise UnsupportedPaymentProviderError(
                f"Unsupported payment gateway provider: {provider_slug}"
            )
        return gateway

    # -----------------------------------------------------------------
    # Health-aware lookup (new)
    # -----------------------------------------------------------------

    def get_healthy_gateway(self, provider_slug: str) -> PaymentGatewayPort:
        """Return the gateway only if its circuit breaker allows a request.

        Raises ``ProviderUnavailableError`` when the breaker is OPEN and
        no probe slots remain.
        """
        gateway = self.get_gateway_for_provider(provider_slug)
        breaker = circuit_breaker_registry.get(self._normalize_slug(provider_slug))
        if not breaker.allow_request():
            raise ProviderUnavailableError(provider_slug)
        return gateway

    def get_gateway_with_fallback(
        self,
        preferred_slug: str,
        *,
        eligible_slugs: list[str] | None = None,
    ) -> tuple[str, PaymentGatewayPort]:
        """Try ``preferred_slug`` first; if its breaker is OPEN, fall back
        to the healthiest alternative from ``eligible_slugs``.

        Returns a ``(slug, gateway)`` tuple so the caller knows which
        provider was actually selected.

        Raises ``AllProvidersUnavailableError`` if nothing is available.
        """
        preferred_norm = self._normalize_slug(preferred_slug)

        # Try the preferred provider first.
        breaker = circuit_breaker_registry.get(preferred_norm)
        if breaker.allow_request():
            gateway = self._gateways.get(preferred_slug.lower()) or self._gateways.get(preferred_norm)
            if gateway is not None:
                return preferred_norm, gateway

        # Build fallback list (all registered minus preferred, filtered by
        # eligible_slugs if provided).
        candidates = eligible_slugs or list(self._gateways.keys())
        fallbacks: list[tuple[str, HealthSnapshot]] = []
        for slug in candidates:
            norm = self._normalize_slug(slug)
            if norm == preferred_norm:
                continue
            if norm not in self._gateways:
                continue
            snap = circuit_breaker_registry.get(norm).health_snapshot()
            fallbacks.append((norm, snap))

        # Sort by health: CLOSED first, then HALF_OPEN, then by lowest failure rate.
        _state_rank = {CircuitState.CLOSED: 0, CircuitState.HALF_OPEN: 1, CircuitState.OPEN: 2}
        fallbacks.sort(key=lambda t: (_state_rank[t[1].state], t[1].failure_rate))

        attempted = [preferred_norm]
        for slug, snap in fallbacks:
            attempted.append(slug)
            fb_breaker = circuit_breaker_registry.get(slug)
            if fb_breaker.allow_request():
                logger.warning(
                    "payment_provider.fallback preferred=%s actual=%s reason=circuit_open",
                    preferred_slug,
                    slug,
                )
                return slug, self._gateways[slug]

        raise AllProvidersUnavailableError(attempted)

    # -----------------------------------------------------------------
    # Health introspection
    # -----------------------------------------------------------------

    def provider_health(self) -> list[HealthSnapshot]:
        """Return health snapshots for every registered gateway."""
        return [
            circuit_breaker_registry.get(slug).health_snapshot()
            for slug in self._gateways
        ]

    def registered_gateways(self) -> list[tuple[str, PaymentGatewayPort]]:
        return list(self._gateways.items())


def _is_braintree_enabled() -> bool:
    """Return True when the `payments.braintree` feature flag is enabled.

    Evaluated without a user/workspace context (global gate). When the flag is
    missing, the safe default is False — Braintree should never auto-enable.
    Failures during evaluation also fail closed so a flag-service outage cannot
    accidentally expose the disabled gateway.
    """
    try:
        from components.shared_platform.application.providers.feature_flags_provider import (
            get_feature_flags_provider,
        )
        is_feature_enabled = get_feature_flags_provider().is_feature_enabled
    except Exception:  # pragma: no cover - import-time safety
        return False
    try:
        return bool(is_feature_enabled("payments.braintree"))
    except Exception:  # pragma: no cover - flag service outage
        return False


def make_payment_gateway_provider() -> PaymentGatewayProviderPort:
    return PaymentGatewayProvider()
