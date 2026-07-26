"""CloudAssetEntity — an immutable cloud-resource node in the asset graph."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from components.cloud_graph.domain.value_objects.enums import Exposure


@dataclass(frozen=True)
class CloudAssetEntity:
    id: UUID
    workspace_id: UUID
    provider: str
    arn: str  # globally-unique resource id — the dedup identity within a workspace
    asset_urn: str  # AssetUrn.value — the cross-pillar correlation key (== a Finding's)
    resource_type: str
    exposure: Exposure
    first_seen_at: datetime
    last_seen_at: datetime
    aws_account_link_id: UUID | None = None
    region: str = ""
    name: str = ""
    attributes: dict = field(default_factory=dict)
    is_deleted: bool = False

    def __post_init__(self) -> None:
        if not self.arn:
            raise ValueError("CloudAssetEntity.arn is required")
        if not self.asset_urn:
            raise ValueError("CloudAssetEntity.asset_urn is required")
        if not self.resource_type:
            raise ValueError("CloudAssetEntity.resource_type is required")

    @property
    def is_public(self) -> bool:
        return self.exposure is Exposure.PUBLIC
