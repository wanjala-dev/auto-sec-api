"""Notifications bounded-context domain errors.

Maps to the shared taxonomy in ``components.shared_kernel.domain.errors``.
"""

from __future__ import annotations

from components.shared_kernel.domain.errors import (
    DomainError,
    ValidationError,
)


class NotificationDomainError(DomainError):
    """Base error for notification domain workflows."""


class NotificationValidationError(NotificationDomainError, ValidationError):
    """Notification data does not satisfy preconditions."""
