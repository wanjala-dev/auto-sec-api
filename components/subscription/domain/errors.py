"""Domain errors for the subscription bounded context.

No Django / DRF imports — extends the shared kernel taxonomy.
"""

from __future__ import annotations

from components.shared_kernel.domain.errors import (
    ConflictError,
    DomainError,
    NotFoundError,
    ValidationError,
)


class SubscriptionError(DomainError):
    """Base class for all subscription domain errors."""


class PlanNotFoundError(SubscriptionError, NotFoundError):
    """Raised when a plan cannot be found."""


class QuotaExceededError(SubscriptionError, ValidationError):
    """Raised when a plan quota is exceeded (projects, tasks, members)."""


class PlanChangeNotAllowedError(SubscriptionError, ValidationError):
    """Raised when a plan change is not valid (e.g. downgrade with overages)."""


class SubscriptionNotActiveError(SubscriptionError, ValidationError):
    """Raised when an operation requires an active subscription."""


class SubscriptionAlreadyActiveError(SubscriptionError, ConflictError):
    """Raised when trying to create a subscription that already exists."""
