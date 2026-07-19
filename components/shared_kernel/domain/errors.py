"""Shared exception taxonomy for the explicit architecture.

Categories
----------
- **DomainError** — business invariant / rule violations
  - **ValidationError** — input or state does not satisfy preconditions
  - **NotFoundError** — an aggregate or entity cannot be located
  - **ConflictError** — idempotency clash or concurrent-write conflict
- **ApplicationError** — orchestration-layer failures
  - **IntegrationError** — a secondary adapter / external service failed
  - **AuthorizationError** — caller lacks permission for the operation

Each context can subclass these to add domain-specific semantics
(e.g. ``PaymentMethodNotFoundError(NotFoundError)``), but controllers
and middleware can catch at the taxonomy level for uniform HTTP mapping.
"""

from __future__ import annotations


# ── Domain errors ───────────────────────────────────────────────────────


class DomainError(Exception):
    """Base error for domain invariant violations."""


class ValidationError(DomainError, ValueError):
    """Input or state does not satisfy business preconditions.

    Also extends ``ValueError`` for backward compatibility with existing
    controller ``except ValueError`` catch blocks during the migration.
    """


class NotFoundError(DomainError, LookupError):
    """An aggregate, entity, or resource could not be located.

    Also extends ``LookupError`` for backward compatibility with existing
    ``except (ObjectDoesNotExist, LookupError)`` catch blocks.
    """


class ConflictError(DomainError):
    """Idempotency clash, concurrent-write conflict, or duplicate."""


# ── Application errors ──────────────────────────────────────────────────


class ApplicationError(Exception):
    """Base error for application-layer orchestration failures."""


class IntegrationError(ApplicationError):
    """A secondary adapter or external service call failed.

    Attributes
    ----------
    service : str | None
        Name of the failing service (e.g. ``"stripe"``, ``"braintree"``).
    """

    def __init__(self, message: str = "", *, service: str | None = None) -> None:
        super().__init__(message)
        self.service = service


class AuthorizationError(ApplicationError):
    """Caller lacks permission for the requested operation."""


class ConfigurationError(ApplicationError):
    """A required port or adapter is not wired / configured."""
