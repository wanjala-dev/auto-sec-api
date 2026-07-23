"""Backfill the provenance graph from workspace memberships (grants).

``WorkspaceMembership.role`` is an internal *grant*: it says what a member can
do in the workspace. We project each active membership into an ``AccessGrant``
edge from the member to the workspace resource, mapping the RBAC role to a
permission set. This is the source that populates the *potential* side of the
graph — and therefore the least-privilege query (a member granted admin who
never acts shows up as an unused admin grant).

Read-only against membership rows; idempotent on the active-grant unique key.
"""

from __future__ import annotations

import logging
from uuid import UUID

from components.provenance.infrastructure.services._projection import (
    SOURCE_INTERNAL,
    upsert_human_actor,
)
from infrastructure.persistence.provenance.models import AccessGrant, ProvenanceResource
from infrastructure.persistence.workspaces.models import WorkspaceMembership

logger = logging.getLogger(__name__)

# RBAC role -> permission set on the workspace resource.
_ROLE_PERMISSIONS = {
    "owner": ["read", "write", "execute", "admin"],
    "admin": ["read", "write", "execute", "admin"],
    "member": ["read", "write"],
    "viewer": ["read"],
}


def _upsert_workspace_resource(workspace_id: UUID, workspace) -> tuple[ProvenanceResource, bool]:
    return ProvenanceResource.objects.get_or_create(
        workspace_id=workspace_id,
        source_system=SOURCE_INTERNAL,
        external_ref=f"workspaces.workspace:{workspace_id}"[:512],
        defaults={
            "resource_type": "workspace",
            "display_name": (getattr(workspace, "name", "") or "workspace")[:255],
        },
    )


def backfill_from_memberships(*, workspace_id: UUID, batch_size: int = 500) -> dict[str, int]:
    """Project active workspace memberships into ``AccessGrant`` edges.

    Returns per-kind counts of newly created rows. Idempotent: a second run
    returns zeros for the created kinds.
    """
    memberships = WorkspaceMembership.objects.filter(workspace_id=workspace_id).select_related("user", "workspace")
    counts = {"scanned": 0, "actors": 0, "resources": 0, "grants": 0}
    actor_cache: dict = {}
    workspace_resource = None

    for membership in memberships.iterator(chunk_size=batch_size):
        counts["scanned"] += 1
        if workspace_resource is None:
            workspace_resource, resource_created = _upsert_workspace_resource(workspace_id, membership.workspace)
            counts["resources"] += int(resource_created)

        actor, actor_created = upsert_human_actor(workspace_id, membership.user, actor_cache)
        counts["actors"] += int(actor_created)

        _, grant_created = AccessGrant.objects.get_or_create(
            workspace_id=workspace_id,
            actor=actor,
            resource=workspace_resource,
            scope="workspace",
            revoked_at__isnull=True,
            defaults={
                "permissions": _ROLE_PERMISSIONS.get(membership.role, ["read"]),
                "source": f"membership:{membership.role}",
            },
        )
        counts["grants"] += int(grant_created)

    logger.info(
        "provenance_membership_backfill workspace_id=%s scanned=%s actors=%s resources=%s grants=%s",
        workspace_id,
        counts["scanned"],
        counts["actors"],
        counts["resources"],
        counts["grants"],
    )
    return counts
