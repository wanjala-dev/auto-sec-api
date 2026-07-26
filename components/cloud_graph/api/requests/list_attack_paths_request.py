"""Input DTO for the attack-path read API — parses + validates query params."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from rest_framework.exceptions import ValidationError

from components.cloud_graph.application.queries.list_attack_paths_query import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    ListAttackPathsQuery,
)
from components.cloud_graph.domain.value_objects.attack_path import AttackPathCategory


def _valid_category(raw) -> str | None:
    value = (raw or "").strip().lower()
    if not value:
        return None
    valid = {c.value for c in AttackPathCategory}
    if value not in valid:
        raise ValidationError({"category": f"must be one of {sorted(valid)}"})
    return value


def _float_param(raw):
    if raw in (None, ""):
        return None
    try:
        return max(0.0, min(100.0, float(raw)))
    except (TypeError, ValueError):
        raise ValidationError({"min_score": "must be a number"})


def _int_param(raw, *, default: int, minimum: int, maximum: int):
    if raw in (None, ""):
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise ValidationError({"limit": "must be an integer"})
    return max(minimum, min(maximum, value))


@dataclass(frozen=True)
class ListAttackPathsRequest:
    workspace_id: UUID
    category: str | None
    min_score: float | None
    limit: int

    @classmethod
    def from_request(cls, request, workspace_id) -> ListAttackPathsRequest:
        qp = request.query_params
        return cls(
            workspace_id=workspace_id,
            category=_valid_category(qp.get("category")),
            min_score=_float_param(qp.get("min_score")),
            limit=_int_param(qp.get("limit"), default=DEFAULT_LIMIT, minimum=1, maximum=MAX_LIMIT),
        )

    def to_query(self) -> ListAttackPathsQuery:
        return ListAttackPathsQuery(
            workspace_id=self.workspace_id,
            category=self.category,
            min_score=self.min_score,
            limit=self.limit,
        )
