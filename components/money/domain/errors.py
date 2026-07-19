"""Domain errors for the money / currency context.

Inherits from the shared exception taxonomy so controllers and
middleware can catch at the :class:`DomainError` level for uniform
HTTP mapping.
"""

from __future__ import annotations

from components.shared_kernel.domain.errors import (
    ApplicationError,
    DomainError,
    ValidationError,
)


class CurrencyError(DomainError):
    """Base class for currency-related domain errors."""


class UnsupportedCurrencyError(CurrencyError, ValidationError):
    """Raised when a currency code is outside the platform allowlist."""


class CurrencyMismatchError(CurrencyError, ValidationError):
    """Raised when two related records disagree on currency.

    e.g. a Transaction whose currency does not match the settlement
    currency of the WorkspacePaymentMethod it is being routed through.
    """


class StripeAccountCurrencyUnavailableError(ApplicationError):
    """Raised when we cannot resolve a currency from a Stripe account.

    Examples: the account has been deleted, access was revoked, or
    Stripe has not yet returned ``default_currency`` on a freshly
    onboarded account.
    """
