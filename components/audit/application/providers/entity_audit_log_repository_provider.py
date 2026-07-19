"""Provider for the entity audit-log repository.

Cross-context callers (recycle_bin) consume this provider instead of
importing
``components.audit.infrastructure.repositories.entity_audit_log_repository``
directly.
"""

from __future__ import annotations

from typing import Any


class EntityAuditLogRepositoryProvider:
    def repository(self) -> Any:
        from components.audit.infrastructure.repositories.entity_audit_log_repository import (
            EntityAuditLogRepository,
        )

        return EntityAuditLogRepository()


_default = EntityAuditLogRepositoryProvider()


def get_entity_audit_log_repository_provider() -> EntityAuditLogRepositoryProvider:
    return _default
