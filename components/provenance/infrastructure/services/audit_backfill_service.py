"""Backfill the provenance graph from the internal audit trail.

This is Slice 0's "zero new integrations" data source: every internal edit
already lands in ``EntityAuditLog`` (a human/service actor changed a field on
an entity at a time). We project those rows into the graph:

* the audit ``actor`` -> a ``ProvenanceActor`` (``source_system="internal"``);
* the audited entity (``content_type`` + ``object_id``) -> a ``ProvenanceResource``;
* the row itself -> a ``ProvenanceEvent`` keyed idempotently on the audit row id.

Backfills are an infrastructure concern (see the persistence rule —
"infrastructure/management/: backfills, schema"). Read-only against the audit
trail; idempotent — re-running projects no duplicates.
"""

from __future__ import annotations

import logging
from datetime import datetime
from uuid import UUID

from infrastructure.persistence.audit.models import EntityAuditLog
from infrastructure.persistence.provenance.models import (
    ProvenanceActor,
    ProvenanceEvent,
    ProvenanceResource,
)

logger = logging.getLogger(__name__)

_SOURCE = "internal"


def _upsert_actor(workspace_id: UUID, user, cache: dict) -> tuple[ProvenanceActor, bool]:
    if user.id in cache:
        return cache[user.id], False
    actor, created = ProvenanceActor.objects.get_or_create(
        workspace_id=workspace_id,
        source_system=_SOURCE,
        external_ref=str(user.id),
        defaults={
            "actor_type": "human",
            "display_name": (user.get_username() or "")[:255],
            "user": user,
        },
    )
    cache[user.id] = actor
    return actor, created


def _upsert_resource(workspace_id: UUID, content_type, object_id: str, cache: dict) -> tuple[ProvenanceResource, bool]:
    external_ref = f"{content_type.app_label}.{content_type.model}:{object_id}"[:512]
    if external_ref in cache:
        return cache[external_ref], False
    resource, created = ProvenanceResource.objects.get_or_create(
        workspace_id=workspace_id,
        source_system=_SOURCE,
        external_ref=external_ref,
        defaults={
            "resource_type": content_type.model[:64],
            "display_name": f"{content_type.model} {object_id}"[:255],
        },
    )
    cache[external_ref] = resource
    return resource, created


def backfill_from_audit_log(
    *, workspace_id: UUID, since: datetime | None = None, batch_size: int = 500
) -> dict[str, int]:
    """Project ``EntityAuditLog`` rows for a workspace into the graph.

    Returns per-kind counts of newly created rows plus how many audit rows were
    scanned. Idempotent: a second run returns zeros for the created kinds.
    """
    rows = EntityAuditLog.objects.filter(workspace_id=workspace_id, actor__isnull=False).select_related(
        "actor", "content_type"
    )
    if since is not None:
        rows = rows.filter(created_at__gte=since)

    counts = {"scanned": 0, "actors": 0, "resources": 0, "events": 0}
    actor_cache: dict = {}
    resource_cache: dict = {}

    for row in rows.iterator(chunk_size=batch_size):
        counts["scanned"] += 1
        actor, actor_created = _upsert_actor(workspace_id, row.actor, actor_cache)
        resource, resource_created = _upsert_resource(workspace_id, row.content_type, row.object_id, resource_cache)
        counts["actors"] += int(actor_created)
        counts["resources"] += int(resource_created)

        _, event_created = ProvenanceEvent.objects.get_or_create(
            workspace_id=workspace_id,
            origin=ProvenanceEvent.Origin.AUDIT_LOG,
            origin_id=str(row.id),
            defaults={
                "actor": actor,
                "resource": resource,
                "action": f"update:{row.field_name}" if row.field_name else "update",
                "occurred_at": row.created_at,
                "source_system": _SOURCE,
                "metadata": {"field_name": row.field_name},
            },
        )
        counts["events"] += int(event_created)

    logger.info(
        "provenance_audit_backfill workspace_id=%s scanned=%s actors=%s resources=%s events=%s",
        workspace_id,
        counts["scanned"],
        counts["actors"],
        counts["resources"],
        counts["events"],
    )
    return counts
