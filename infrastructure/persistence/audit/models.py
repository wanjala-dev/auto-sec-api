"""EntityAuditLog — append-only, field-level audit trail for any entity.

Uses Django's ``GenericForeignKey`` so one table covers campaigns,
events, recipients, projects, anything with a primary key. Add a
new entity type by just logging against it — no schema change. Add
a new tracked field by passing a different ``field_name`` — also
no schema change.

Design notes
------------
* Append-only. No updates, no deletes from application code. If a row
  is wrong, add a compensating row rather than rewriting history.
* ``object_id`` is stored as ``CharField(64)`` so it can hold either a
  UUID string or a stringified integer primary key. Filtering by
  ``(content_type_id, object_id)`` is O(1) via the composite index.
* ``previous_value`` / ``new_value`` are ``JSONField`` so any
  serialisable type works — Decimals are stored as strings by
  ``log_field_change`` to preserve precision.
* ``workspace`` is the tenant column. All queries should scope to the
  current workspace so an admin can only see their own audit log.
* ``actor`` is nullable to permit system-generated events (background
  jobs, reconciliation tasks) that have no user context.
"""

from __future__ import annotations

import uuid

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models


class EntityAuditLog(models.Model):
    """One row per tracked field change on any entity.

    Immutable once written. See the module docstring for the design
    rationale and the companion helper
    ``components.shared_platform.infrastructure.services.audit_log
    .log_field_change`` for the write API.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Tenant scope. Kept as nullable only so historical system events
    # (e.g. from tests or workspace-less operations) don't block
    # insertion; in practice every business edit carries a workspace.
    workspace = models.ForeignKey(
        "workspaces.Workspace",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="audit_entries",
    )

    # Polymorphic target — which entity was changed.
    content_type = models.ForeignKey(
        ContentType,
        on_delete=models.PROTECT,
        related_name="audit_entries",
    )
    object_id = models.CharField(max_length=64)
    content_object = GenericForeignKey("content_type", "object_id")

    # Which field on that entity was changed.
    field_name = models.CharField(max_length=64)

    # Before / after values as JSON. Decimals are serialised as
    # strings by the log helper to preserve precision.
    previous_value = models.JSONField(null=True, blank=True)
    new_value = models.JSONField(null=True, blank=True)

    # Who did it. Nullable to permit system / background job writes.
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="audit_entries",
    )

    # Optional human-readable reason the editor supplied. Captured
    # from a ``edit_reason`` field on the PATCH payload when present.
    reason = models.TextField(blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["content_type", "object_id", "-created_at"],
                name="audit_entity_idx",
            ),
            models.Index(
                fields=["workspace", "-created_at"],
                name="audit_workspace_idx",
            ),
            models.Index(
                fields=["actor", "-created_at"],
                name="audit_actor_idx",
            ),
            models.Index(
                fields=["content_type", "object_id", "field_name", "-created_at"],
                name="audit_entity_field_idx",
            ),
        ]

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        return (
            f"{self.content_type.app_label}.{self.content_type.model}"
            f"[{self.object_id}].{self.field_name} "
            f"→ {self.new_value!r} ({self.created_at.isoformat()})"
        )
