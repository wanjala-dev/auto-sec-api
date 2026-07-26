"""CloudAssetEdgeEntity — an immutable typed relationship between two assets."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from components.cloud_graph.domain.value_objects.enums import AssetRelation


@dataclass(frozen=True)
class CloudAssetEdgeEntity:
    id: UUID
    workspace_id: UUID
    src_asset_id: UUID
    dst_asset_id: UUID
    relation: AssetRelation
    last_seen_at: datetime
    attributes: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.src_asset_id == self.dst_asset_id:
            raise ValueError("CloudAssetEdgeEntity cannot connect an asset to itself")
