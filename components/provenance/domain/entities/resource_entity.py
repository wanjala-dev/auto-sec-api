"""Resource node — a thing acted upon (system, store, repo, channel, bucket)."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from components.provenance.domain.value_objects.enums import SourceSystem
from components.shared_kernel.domain.security import AssetUrn


@dataclass(frozen=True)
class ResourceEntity:
    id: UUID
    workspace_id: UUID
    resource_type: str
    source_system: SourceSystem
    external_ref: str
    display_name: str = ""

    def __post_init__(self) -> None:
        if not self.resource_type:
            raise ValueError("ResourceEntity.resource_type is required")
        if not self.external_ref:
            raise ValueError("ResourceEntity.external_ref is required")

    @property
    def asset_urn(self) -> AssetUrn:
        """The canonical cross-pillar identity for this resource (ADR 0004 D2).

        Derived from the immutable ``(source_system, external_ref)`` identity — the
        same value the persistence layer stamps on the row and that a finding uses to
        correlate to this graph node.
        """
        return AssetUrn.canonical(self.source_system.value, self.external_ref)
