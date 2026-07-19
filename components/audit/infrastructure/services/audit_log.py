"""Convenience facade over the audit use cases.

Callers (campaign/event/recipient PATCH handlers) import
``log_field_change`` and ``get_entity_history`` from this module. The
facade wires the port to its ORM adapter lazily so individual call
sites don't have to know about dependency injection.

For tests, inject a custom port via the provider instead of
monkey-patching these helpers.
"""

from __future__ import annotations

from typing import Any

from components.audit.application.use_cases.get_entity_history_use_case import (
    GetEntityHistoryUseCase,
)
from components.audit.application.use_cases.log_field_change_use_case import (
    LogFieldChangeUseCase,
)
from components.audit.domain.entities.audit_entry_entity import AuditEntry
from components.audit.infrastructure.repositories.entity_audit_log_repository import (
    EntityAuditLogRepository,
)


def _use_case() -> LogFieldChangeUseCase:
    return LogFieldChangeUseCase(audit_log=EntityAuditLogRepository())


def _history_use_case() -> GetEntityHistoryUseCase:
    return GetEntityHistoryUseCase(audit_log=EntityAuditLogRepository())


def _entity_type_for(instance: Any) -> str:
    meta = getattr(instance, "_meta", None)
    if meta is None:
        return ""
    return f"{meta.app_label}.{meta.model_name}"


def _infer_workspace_id(instance: Any) -> str | None:
    for attr in ("workspace_id", "workspace"):
        if hasattr(instance, attr):
            value = getattr(instance, attr, None)
            if value is None:
                continue
            pk = getattr(value, "pk", value)
            return str(pk) if pk is not None else None
    return None


def log_field_change(
    *,
    instance: Any,
    field_name: str,
    previous_value: Any,
    new_value: Any,
    actor: Any = None,
    reason: str = "",
) -> AuditEntry | None:
    """Record a field change for the given ORM instance.

    Returns the persisted ``AuditEntry`` or ``None`` when the edit
    is a no-op (identical values). The use case handles
    JSON-normalisation and no-op suppression.
    """

    actor_id = None
    if actor is not None:
        actor_pk = getattr(actor, "pk", None)
        if actor_pk is not None:
            actor_id = str(actor_pk)
    return _use_case().execute(
        workspace_id=_infer_workspace_id(instance),
        entity_type=_entity_type_for(instance),
        entity_id=str(getattr(instance, "pk", "")),
        field_name=field_name,
        previous_value=previous_value,
        new_value=new_value,
        actor_id=actor_id,
        reason=reason,
    )


def get_entity_history(
    *,
    instance: Any,
    field_name: str | None = None,
    limit: int | None = None,
) -> list[AuditEntry]:
    return _history_use_case().execute(
        entity_type=_entity_type_for(instance),
        entity_id=str(getattr(instance, "pk", "")),
        field_name=field_name,
        limit=limit,
    )
