"""Shared projection helpers for the internal graph backfills.

Both the audit-log and identity backfills project internal humans onto the
same ``ProvenanceActor`` identity, so the upsert lives here once (DRY) and is
reused — a human is one node regardless of which source first observed them.
"""

from __future__ import annotations

from uuid import UUID

from infrastructure.persistence.provenance.models import ProvenanceActor

SOURCE_INTERNAL = "internal"


def upsert_human_actor(workspace_id: UUID, user, cache: dict) -> tuple[ProvenanceActor, bool]:
    """Get-or-create the internal ``ProvenanceActor`` for a ``CustomUser``.

    ``cache`` dedupes within a single backfill run so the same user is upserted
    once even across thousands of rows.
    """
    if user.id in cache:
        return cache[user.id], False
    actor, created = ProvenanceActor.objects.get_or_create(
        workspace_id=workspace_id,
        source_system=SOURCE_INTERNAL,
        external_ref=str(user.id),
        defaults={
            "actor_type": "human",
            "display_name": (user.get_username() or "")[:255],
            "user": user,
        },
    )
    cache[user.id] = actor
    return actor, created
