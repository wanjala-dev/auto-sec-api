"""Django ORM adapter implementing ``AuditLogPort``.

This is the only module in the audit context allowed to import the
``EntityAuditLog`` Django model. Application-layer use cases depend
on ``AuditLogPort`` and receive this adapter via the provider.
"""

from __future__ import annotations

from typing import Any

from components.audit.application.ports.audit_log_port import AuditLogPort
from components.audit.domain.entities.audit_entry_entity import AuditEntry


def _entry_to_domain(row) -> AuditEntry:
    ct = row.content_type
    actor = row.actor
    actor_display = ""
    if actor is not None:
        full = " ".join(
            part
            for part in (
                getattr(actor, "first_name", "") or "",
                getattr(actor, "last_name", "") or "",
            )
            if part
        )
        actor_display = full or getattr(actor, "email", "") or getattr(actor, "username", "") or ""
    return AuditEntry(
        id=str(row.id),
        workspace_id=str(row.workspace_id) if row.workspace_id else None,
        entity_type=f"{ct.app_label}.{ct.model}" if ct else "",
        entity_id=row.object_id,
        field_name=row.field_name,
        previous_value=row.previous_value,
        new_value=row.new_value,
        actor_id=str(actor.id) if actor else None,
        actor_display=actor_display,
        reason=row.reason or "",
        created_at=row.created_at,
    )


class EntityAuditLogRepository(AuditLogPort):
    """ORM-backed implementation of the audit log port."""

    def record(
        self,
        *,
        workspace_id: str | None,
        entity_type: str,
        entity_id: str,
        field_name: str,
        previous_value: Any,
        new_value: Any,
        actor_id: str | None,
        reason: str,
    ) -> AuditEntry | None:
        from django.contrib.contenttypes.models import ContentType
        from infrastructure.persistence.audit.models import EntityAuditLog

        app_label, _, model_name = entity_type.partition(".")
        if not model_name:
            # Accept a bare model name (sponsorship fallback) by
            # deferring to ContentType's natural-key lookup.
            ct = ContentType.objects.filter(model=entity_type).first()
        else:
            ct = ContentType.objects.filter(
                app_label=app_label, model=model_name
            ).first()
        if ct is None:
            return None

        row = EntityAuditLog.objects.create(
            workspace_id=workspace_id,
            content_type=ct,
            object_id=entity_id,
            field_name=field_name,
            previous_value=previous_value,
            new_value=new_value,
            actor_id=actor_id,
            reason=reason,
        )
        return _entry_to_domain(row)

    def list_for_entity(
        self,
        *,
        entity_type: str,
        entity_id: str,
        field_name: str | None = None,
        limit: int | None = None,
    ) -> list[AuditEntry]:
        from django.contrib.contenttypes.models import ContentType
        from infrastructure.persistence.audit.models import EntityAuditLog

        app_label, _, model_name = entity_type.partition(".")
        if not model_name:
            ct = ContentType.objects.filter(model=entity_type).first()
        else:
            ct = ContentType.objects.filter(
                app_label=app_label, model=model_name
            ).first()
        if ct is None:
            return []

        qs = (
            EntityAuditLog.objects.filter(
                content_type=ct, object_id=str(entity_id)
            )
            .select_related("actor", "content_type")
        )
        if field_name:
            qs = qs.filter(field_name=field_name)
        if limit:
            qs = qs[:limit]
        return [_entry_to_domain(row) for row in qs]
