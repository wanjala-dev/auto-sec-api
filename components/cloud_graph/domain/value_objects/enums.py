"""Value objects for the cloud asset graph."""

from __future__ import annotations

from enum import Enum


class Exposure(str, Enum):
    """How reachable a resource is — the first leg of most attack paths."""

    PUBLIC = "public"
    INTERNAL = "internal"
    PRIVATE = "private"

    @classmethod
    def from_value(cls, value) -> Exposure:
        try:
            return cls(str(value or "").strip().lower())
        except ValueError:
            return cls.PRIVATE


class AssetRelation(str, Enum):
    """Typed edges between resources — the graph's traversable relationships.

    The spike's attack-path CTE queries (§6) walk these: e.g. an internet-exposed
    instance ``attached_to`` a role that ``has_policy`` admin.
    """

    CAN_ASSUME = "can_assume"
    ATTACHED_TO = "attached_to"
    ALLOWS_INGRESS_FROM = "allows_ingress_from"
    HAS_POLICY = "has_policy"
    IN_SUBNET = "in_subnet"
    ROUTES_TO_IGW = "routes_to_igw"
    READS_BUCKET = "reads_bucket"

    @classmethod
    def from_value(cls, value) -> AssetRelation:
        return cls(str(value or "").strip().lower())
