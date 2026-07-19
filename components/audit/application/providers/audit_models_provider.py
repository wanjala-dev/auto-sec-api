"""Audit ORM model provider.

Exposes the Django ORM model classes from ``infrastructure.persistence.audit``
through lazy properties so controllers never import the persistence package
directly. Keeps the controller / application layer free of Django imports at
module load time, in line with Explicit Architecture.

Only stdlib + typing imports at module top — every concrete ORM import lives
inside a method body.
"""

from __future__ import annotations

from typing import Any


class AuditModelsProvider:
    """Lazy accessor for ORM models in ``infrastructure.persistence.audit``."""

    @property
    def EntityAuditLog(self) -> Any:
        from infrastructure.persistence.audit.models import EntityAuditLog
        return EntityAuditLog


_default = AuditModelsProvider()


def get_audit_models_provider() -> AuditModelsProvider:
    """Return the default :class:`AuditModelsProvider` instance."""
    return _default
