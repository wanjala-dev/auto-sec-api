"""Django ORM implementation of :class:`ProvenanceGraphPort`.

Read-only, workspace-scoped. Eager-loads every FK the mappers touch so a
graph read is a bounded number of queries, not N+1 (see performance rule §1).

Slice 0 keeps traversal shallow: the hall-tree is depth-1 (an actor and the
resources it touched). Deeper multi-hop traversal — and, if depth ever
demands it, a dedicated graph store — is a later slice; ``max_depth`` is
threaded through now so the contract does not change when it lands.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import UUID

from django.db.models import Count, Max
from django.utils import timezone

from components.provenance.application.ports.provenance_graph_port import ProvenanceGraphPort
from components.provenance.application.queries.graph_queries import (
    AccessReviewRow,
    HallTree,
    HallTreeNode,
    LeastPrivilegeGap,
    VendorBlastRadius,
)
from components.provenance.mappers.db.provenance_mapper import (
    to_actor_entity,
    to_event_entity,
    to_grant_entity,
    to_resource_entity,
)
from infrastructure.persistence.provenance.models import (
    AccessGrant,
    ProvenanceActor,
    ProvenanceEvent,
    ProvenanceResource,
)

# How many recent events a blast-radius read returns (the "what did it actually
# do" panel is a recent slice, not the full history).
_RECENT_EVENT_LIMIT = 100


class DjangoProvenanceRepository(ProvenanceGraphPort):
    def vendor_blast_radius(self, *, workspace_id: UUID, actor_id: UUID) -> VendorBlastRadius:
        actor = ProvenanceActor.objects.select_related("workspace").get(id=actor_id, workspace_id=workspace_id)
        grants = list(
            AccessGrant.objects.filter(
                workspace_id=workspace_id, actor_id=actor_id, revoked_at__isnull=True
            ).select_related("resource")
        )
        events = list(
            ProvenanceEvent.objects.filter(workspace_id=workspace_id, actor_id=actor_id)
            .select_related("resource")
            .order_by("-occurred_at")[:_RECENT_EVENT_LIMIT]
        )
        # Distinct resources reachable via a grant (the "potential").
        reachable = {g.resource_id: g.resource for g in grants}
        return VendorBlastRadius(
            actor=to_actor_entity(actor),
            grants=tuple(to_grant_entity(g) for g in grants),
            recent_events=tuple(to_event_entity(e) for e in events),
            reachable_resources=tuple(to_resource_entity(r) for r in reachable.values()),
        )

    def access_review(self, *, workspace_id: UUID, resource_id: UUID) -> list[AccessReviewRow]:
        grants = list(
            AccessGrant.objects.filter(
                workspace_id=workspace_id, resource_id=resource_id, revoked_at__isnull=True
            ).select_related("actor")
        )
        last_by_actor: dict[UUID, datetime] = {
            row["actor_id"]: row["last"]
            for row in ProvenanceEvent.objects.filter(workspace_id=workspace_id, resource_id=resource_id)
            .values("actor_id")
            .annotate(last=Max("occurred_at"))
        }
        return [
            AccessReviewRow(
                actor=to_actor_entity(g.actor),
                grant=to_grant_entity(g),
                last_activity_at=last_by_actor.get(g.actor_id),
            )
            for g in grants
        ]

    def hall_tree(self, *, workspace_id: UUID, actor_id: UUID, since: datetime, max_depth: int = 3) -> HallTree:
        actor = ProvenanceActor.objects.get(id=actor_id, workspace_id=workspace_id)
        touched = list(
            ProvenanceEvent.objects.filter(workspace_id=workspace_id, actor_id=actor_id, occurred_at__gte=since)
            .values("resource_id")
            .annotate(count=Count("id"), last=Max("occurred_at"))
        )
        resources = {r.id: r for r in ProvenanceResource.objects.filter(id__in=[t["resource_id"] for t in touched])}
        roots = [
            HallTreeNode(
                resource=to_resource_entity(resources[t["resource_id"]]),
                event_count=t["count"],
                last_event_at=t["last"],
                children=(),
            )
            for t in touched
            if t["resource_id"] in resources
        ]
        roots.sort(key=lambda n: n.last_event_at or since, reverse=True)
        return HallTree(actor=to_actor_entity(actor), since=since, roots=tuple(roots))

    def least_privilege_gaps(self, *, workspace_id: UUID, unused_days: int = 30) -> list[LeastPrivilegeGap]:
        cutoff = timezone.now() - timedelta(days=unused_days)
        grants = list(
            AccessGrant.objects.filter(workspace_id=workspace_id, revoked_at__isnull=True).select_related(
                "actor", "resource"
            )
        )
        # (actor, resource) pairs that saw any activity in the window.
        used_pairs: set[tuple[UUID, UUID]] = set(
            ProvenanceEvent.objects.filter(workspace_id=workspace_id, occurred_at__gte=cutoff)
            .values_list("actor_id", "resource_id")
            .distinct()
        )
        return [
            LeastPrivilegeGap(
                actor=to_actor_entity(g.actor),
                grant=to_grant_entity(g),
                resource=to_resource_entity(g.resource),
                unused_days=unused_days,
                workspace_id=workspace_id,
            )
            for g in grants
            if (g.actor_id, g.resource_id) not in used_pairs
        ]
