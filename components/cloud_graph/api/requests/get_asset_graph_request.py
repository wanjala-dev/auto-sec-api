"""Input DTO for the asset-graph read API — parses + validates query params."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from rest_framework.exceptions import ValidationError

from components.cloud_graph.application.queries.get_asset_graph_query import (
    DEFAULT_NODE_LIMIT,
    MAX_NODE_LIMIT,
    GetAssetGraphQuery,
)
from components.cloud_graph.domain.value_objects.enums import Exposure


def _valid_exposure(raw) -> str | None:
    value = (raw or "").strip().lower()
    if not value:
        return None
    valid = {e.value for e in Exposure}
    if value not in valid:
        raise ValidationError({"exposure": f"must be one of {sorted(valid)}"})
    return value


def _int_param(raw, *, default: int, minimum: int, maximum: int) -> int:
    if raw in (None, ""):
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise ValidationError({"limit": "must be an integer"})
    return max(minimum, min(maximum, value))


@dataclass(frozen=True)
class GetAssetGraphRequest:
    workspace_id: UUID
    resource_type: str | None
    exposure: str | None
    limit: int

    @classmethod
    def from_request(cls, request, workspace_id) -> GetAssetGraphRequest:
        qp = request.query_params
        return cls(
            workspace_id=workspace_id,
            resource_type=(qp.get("resource_type") or "").strip() or None,
            exposure=_valid_exposure(qp.get("exposure")),
            limit=_int_param(qp.get("limit"), default=DEFAULT_NODE_LIMIT, minimum=1, maximum=MAX_NODE_LIMIT),
        )

    def to_query(self) -> GetAssetGraphQuery:
        return GetAssetGraphQuery(
            workspace_id=self.workspace_id,
            resource_type=self.resource_type,
            exposure=self.exposure,
            limit=self.limit,
        )
