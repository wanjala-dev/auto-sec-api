"""Django ORM adapter implementing ``AuditLogPort``.

This is the only module in the audit context allowed to import the
``EntityAuditLog`` Django model. Application-layer use cases depend
on ``AuditLogPort`` and receive this adapter via the provider.
"""

from __future__ import annotations

import logging
from typing import Any

from components.audit.application.ports.audit_log_port import AuditLogPort
from components.audit.domain.entities.audit_entry_entity import AuditEntry

logger = logging.getLogger(__name__)


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
            # Accept a bare model name (legacy fallback) by
            # deferring to ContentType's natural-key lookup.
            ct = ContentType.objects.filter(model=entity_type).first()
        else:
            ct = ContentType.objects.filter(app_label=app_label, model=model_name).first()
        if ct is None:
            # Returning None here is a DROPPED AUDIT WRITE. It is kept
            # non-raising so an audit failure can never break the user-facing
            # action it describes — but it must be loud. A silent return is
            # what let every sign_off decision write to nowhere for the life
            # of that feature: the caller passed "signoff.<artifact_type>",
            # no such model existed, and nothing anywhere said so.
            logger.error(
                "entity_audit_log.write_dropped entity_type=%s entity_id=%s field=%s reason=content_type_unresolvable",
                entity_type,
                entity_id,
                field_name,
            )
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
        workspace_id: str | None = None,
        field_name: str | None = None,
        limit: int | None = None,
    ) -> list[AuditEntry]:
        from django.contrib.contenttypes.models import ContentType

        from infrastructure.persistence.audit.models import EntityAuditLog

        app_label, _, model_name = entity_type.partition(".")
        if not model_name:
            ct = ContentType.objects.filter(model=entity_type).first()
        else:
            ct = ContentType.objects.filter(app_label=app_label, model=model_name).first()
        if ct is None:
            return []

        qs = EntityAuditLog.objects.filter(content_type=ct, object_id=str(entity_id)).select_related(
            "actor", "content_type"
        )
        if workspace_id:
            # Tenant scoping. Rows written with workspace=NULL
            # (historical/system events) are deliberately excluded from
            # workspace-scoped reads — they carry no proof of tenancy.
            qs = qs.filter(workspace_id=workspace_id)
        if field_name:
            qs = qs.filter(field_name=field_name)
        if limit:
            qs = qs[:limit]
        return [_entry_to_domain(row) for row in qs]

    def list_for_workspace(
        self,
        *,
        workspace_id: str,
        entity_type: str | None = None,
        field_name: str | None = None,
        actor_id: str | None = None,
        since: Any = None,
        until: Any = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[AuditEntry], int]:
        from django.contrib.contenttypes.models import ContentType

        from infrastructure.persistence.audit.models import EntityAuditLog

        # Tenant scope is mandatory — the workspace_id filter drives the
        # ``audit_workspace_idx`` (workspace, -created_at) index. NULL-
        # workspace (historical/system) rows carry no tenancy proof and
        # are excluded exactly like the per-entity read path.
        qs = EntityAuditLog.objects.filter(workspace_id=workspace_id).select_related("actor", "content_type")

        if entity_type:
            app_label, _, model_name = entity_type.partition(".")
            if model_name:
                ct = ContentType.objects.filter(app_label=app_label, model=model_name).first()
            else:
                ct = ContentType.objects.filter(model=entity_type).first()
            if ct is None:
                # An unknown entity_type filter matches nothing — return
                # an empty, correctly-typed page rather than 400ing.
                return [], 0
            qs = qs.filter(content_type=ct)
        if field_name:
            qs = qs.filter(field_name=field_name)
        if actor_id:
            qs = qs.filter(actor_id=actor_id)
        if since is not None:
            qs = qs.filter(created_at__gte=since)
        if until is not None:
            qs = qs.filter(created_at__lte=until)

        # Count the filtered set BEFORE slicing so the caller can page.
        total = qs.count()

        start = max(0, offset)
        end = start + max(1, limit)
        rows = qs.order_by("-created_at")[start:end]
        return [_entry_to_domain(row) for row in rows], total
