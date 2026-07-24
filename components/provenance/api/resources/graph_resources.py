"""Output DTOs for the provenance graph read endpoints.

Serialize the CQRS query result DTOs into plain JSON-able dicts. The small
per-entity helpers keep the four resource shapes consistent (DRY).
"""

from __future__ import annotations

from dataclasses import dataclass

from components.provenance.application.queries.provenance_graph_query import (
    AccessReviewRow,
    GraphOverview,
    HallTree,
    HallTreeNode,
    LeastPrivilegeGap,
    VendorBlastRadius,
)


def _actor_dict(actor) -> dict:
    return {
        "id": str(actor.id),
        "type": str(actor.actor_type),
        "source_system": str(actor.source_system),
        "external_ref": actor.external_ref,
        "display_name": actor.display_name,
        "user_id": str(actor.user_id) if actor.user_id else None,
    }


def _resource_dict(resource) -> dict:
    return {
        "id": str(resource.id),
        "type": resource.resource_type,
        "source_system": str(resource.source_system),
        "external_ref": resource.external_ref,
        "display_name": resource.display_name,
    }


def _grant_dict(grant) -> dict:
    return {
        "id": str(grant.id),
        "permissions": [str(p) for p in grant.permissions],
        "scope": grant.scope,
        "source": grant.source,
        "is_admin": grant.is_admin,
    }


def _event_dict(event) -> dict:
    return {
        "id": str(event.id),
        "action": event.action,
        "occurred_at": event.occurred_at.isoformat(),
        "source_system": str(event.source_system),
    }


@dataclass(frozen=True)
class GraphOverviewResource:
    result: GraphOverview

    @classmethod
    def from_result(cls, result: GraphOverview) -> GraphOverviewResource:
        return cls(result=result)

    def to_dict(self) -> dict:
        r = self.result
        return {
            "actors": [_actor_dict(a) for a in r.actors],
            "resources": [_resource_dict(x) for x in r.resources],
            "grants": [
                {**_grant_dict(g), "actor_id": str(g.actor_id), "resource_id": str(g.resource_id)} for g in r.grants
            ],
            "activity": [
                {
                    "actor_id": str(e.actor_id),
                    "resource_id": str(e.resource_id),
                    "event_count": e.event_count,
                    "last_event_at": e.last_event_at.isoformat() if e.last_event_at else None,
                }
                for e in r.activity
            ],
            "truncated": r.truncated,
        }


@dataclass(frozen=True)
class BlastRadiusResource:
    result: VendorBlastRadius

    @classmethod
    def from_result(cls, result: VendorBlastRadius) -> BlastRadiusResource:
        return cls(result=result)

    def to_dict(self) -> dict:
        r = self.result
        return {
            "actor": _actor_dict(r.actor),
            "grants": [_grant_dict(g) for g in r.grants],
            "recent_events": [_event_dict(e) for e in r.recent_events],
            "reachable_resources": [_resource_dict(x) for x in r.reachable_resources],
        }


@dataclass(frozen=True)
class AccessReviewResource:
    rows: list[AccessReviewRow]

    @classmethod
    def from_rows(cls, rows: list[AccessReviewRow]) -> AccessReviewResource:
        return cls(rows=list(rows))

    def to_dict(self) -> dict:
        return {
            "rows": [
                {
                    "actor": _actor_dict(row.actor),
                    "grant": _grant_dict(row.grant),
                    "last_activity_at": row.last_activity_at.isoformat() if row.last_activity_at else None,
                }
                for row in self.rows
            ]
        }


def _hall_tree_node_dict(node: HallTreeNode) -> dict:
    return {
        "resource": _resource_dict(node.resource),
        "event_count": node.event_count,
        "last_event_at": node.last_event_at.isoformat() if node.last_event_at else None,
        "children": [_hall_tree_node_dict(child) for child in node.children],
    }


@dataclass(frozen=True)
class HallTreeResource:
    result: HallTree

    @classmethod
    def from_result(cls, result: HallTree) -> HallTreeResource:
        return cls(result=result)

    def to_dict(self) -> dict:
        return {
            "actor": _actor_dict(self.result.actor),
            "since": self.result.since.isoformat(),
            "roots": [_hall_tree_node_dict(node) for node in self.result.roots],
        }


@dataclass(frozen=True)
class LeastPrivilegeResource:
    gaps: list[LeastPrivilegeGap]

    @classmethod
    def from_gaps(cls, gaps: list[LeastPrivilegeGap]) -> LeastPrivilegeResource:
        return cls(gaps=list(gaps))

    def to_dict(self) -> dict:
        return {
            "gaps": [
                {
                    "actor": _actor_dict(gap.actor),
                    "grant": _grant_dict(gap.grant),
                    "resource": _resource_dict(gap.resource),
                    "unused_days": gap.unused_days,
                }
                for gap in self.gaps
            ]
        }
