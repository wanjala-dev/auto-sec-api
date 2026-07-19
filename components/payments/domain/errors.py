from __future__ import annotations

from components.shared_kernel.domain.errors import (
    DomainError,
    IntegrationError,
    NotFoundError,
    ValidationError,
)


class PaymentDomainError(DomainError):
    """Base error for payments-domain workflows."""


class PaymentMethodNotFoundError(PaymentDomainError, NotFoundError):
    """Raised when a payment method cannot be found in the repository."""


class UnsupportedPaymentProviderError(PaymentDomainError, ValidationError):
    """Raised when a workflow is invoked for an unsupported payment provider."""


class PaymentOnboardingConfigurationError(PaymentDomainError, ValidationError):
    """Raised when provider onboarding is misconfigured locally."""


class PaymentValidationError(PaymentDomainError, ValidationError):
    """Payment data does not satisfy business preconditions."""


class SubscriptionError(PaymentDomainError, ValidationError):
    """A subscription operation could not proceed (missing data, invalid state)."""


class PaymentConfigurationError(PaymentDomainError, ValidationError):
    """Required payment infrastructure is not configured (API keys, providers)."""


class PaymentAccountUnavailableError(PaymentDomainError, ValidationError):
    """The organisation's payment account cannot accept charges right now.

    Raised when the provider rejects a charge because the connected account
    is revoked, never finished onboarding, or no longer exists (Stripe
    ``PermissionError`` / ``AuthenticationError``). This is a **per-org
    configuration problem**, NOT a provider outage — it must NOT trip the
    circuit breaker (that would block every other org's checkout) and must
    surface as a 400 (a ``ValidationError`` subclass), not a 5xx (the
    frontend treats >= 500 as "backend unhealthy" and blacks out the app).

    The user-facing message is deliberately donor-safe: it never echoes the
    raw Stripe message, which leaks the secret-key prefix and the internal
    connected-account id. The raw exception is logged server-side only.
    """


class WebhookVerificationError(PaymentDomainError, IntegrationError):
    """Webhook payload could not be verified."""


class PaymentOnboardingError(PaymentDomainError, IntegrationError):
    """Raised when a provider onboarding call fails."""

    def __init__(self, *, stage: str, details: str):
        super().__init__(details)
        self.stage = stage
        self.details = details


class ProviderUnavailableError(PaymentDomainError, IntegrationError):
    """Raised when a provider's circuit breaker is open (too many recent failures)."""

    def __init__(self, provider_slug: str):
        super().__init__(
            f"Payment provider '{provider_slug}' is temporarily unavailable "
            f"due to repeated failures. It will be retried automatically."
        )
        self.provider_slug = provider_slug


class AllProvidersUnavailableError(PaymentDomainError, IntegrationError):
    """Raised when every eligible provider's circuit breaker is open."""

    def __init__(self, attempted_slugs: list[str] | None = None):
        slugs = ", ".join(attempted_slugs) if attempted_slugs else "all"
        super().__init__(
            f"All payment providers are temporarily unavailable "
            f"(attempted: {slugs}). Please try again later."
        )
        self.attempted_slugs = attempted_slugs or []


class RefundValidationError(PaymentDomainError, ValidationError):
    """Refund request does not satisfy business preconditions."""


class InsufficientRefundableAmountError(RefundValidationError):
    """The requested refund amount exceeds the refundable balance."""

    def __init__(self, requested: str, available: str):
        super().__init__(
            f"Requested refund {requested} exceeds refundable amount {available}."
        )
        self.requested = requested
        self.available = available


class DisputeNotFoundError(PaymentDomainError, NotFoundError):
    """A dispute record could not be located."""


class PayoutError(PaymentDomainError, IntegrationError):
    """A payout operation failed."""
