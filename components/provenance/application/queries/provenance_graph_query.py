"""Read-model DTOs for the provenance graph query surface (CQRS).

These are the shapes the port returns and the API resources render. They are
framework-free; the repository assembles them from the ORM.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from components.provenance.domain.entities.actor_entity import ActorEntity
from components.provenance.domain.entities.grant_entity import GrantEntity
from components.provenance.domain.entities.provenance_event_entity import ProvenanceEventEntity
from components.provenance.domain.entities.resource_entity import ResourceEntity


@dataclass(frozen=True)
class VendorBlastRadius:
    """What a vendor/integration actor can reach (grants) vs. actually did (events)."""

    actor: ActorEntity
    grants: tuple[GrantEntity, ...]
    recent_events: tuple[ProvenanceEventEntity, ...]
    reachable_resources: tuple[ResourceEntity, ...]


@dataclass(frozen=True)
class AccessReviewRow:
    """One actor's access to a given resource, grouped by permission tier."""

    actor: ActorEntity
    grant: GrantEntity
    last_activity_at: datetime | None = None


@dataclass(frozen=True)
class HallTreeNode:
    """A node in an actor's provenance tree — a resource it touched + a drill-down."""

    resource: ResourceEntity
    event_count: int
    last_event_at: datetime | None = None
    children: tuple[HallTreeNode, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class HallTree:
    actor: ActorEntity
    since: datetime
    roots: tuple[HallTreeNode, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class LeastPrivilegeGap:
    """A grant with no observed use in the window — an unused-permission signal."""

    actor: ActorEntity
    grant: GrantEntity
    resource: ResourceEntity
    unused_days: int
    workspace_id: UUID


@dataclass(frozen=True)
class ActivityEdge:
    """An actor→resource edge summarising observed events (the *actual*)."""

    actor_id: UUID
    resource_id: UUID
    event_count: int
    last_event_at: datetime | None = None


@dataclass(frozen=True)
class GraphOverview:
    """Bounded whole-workspace snapshot the HUD renders on open.

    Nodes = actors + resources. Edges = grants (potential) + activity (actual).
    ``truncated`` flags that a node/edge cap was hit so the UI can say so rather
    than imply the graph is complete.
    """

    actors: tuple[ActorEntity, ...]
    resources: tuple[ResourceEntity, ...]
    grants: tuple[GrantEntity, ...]
    activity: tuple[ActivityEdge, ...]
    truncated: bool = False
