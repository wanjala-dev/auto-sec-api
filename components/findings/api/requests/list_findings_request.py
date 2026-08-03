"""Input DTO for the findings list API — parses + validates query params."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from rest_framework.exceptions import ValidationError

from components.findings.application.queries.list_findings_query import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    ORDER_CONTEXTUAL_RISK,
    VALID_ORDER_BY,
    ListFindingsQuery,
)
from components.shared_kernel.domain.security import FindingStatus, Severity

# Re-reference the imports so the formatter never strips them as "unused" (they are used
# below in from_request): both are consumed by the order_by parse.
_ORDER_BY_CHOICES = set(VALID_ORDER_BY)
_DEFAULT_ORDER = ORDER_CONTEXTUAL_RISK


def _valid_choice(raw, valid: set[str], field: str) -> str | None:
    value = (raw or "").strip().lower()
    if not value:
        return None
    if value not in valid:
        raise ValidationError({field: f"must be one of {sorted(valid)}"})
    return value


def _int_param(raw, *, default: int, minimum: int, maximum: int, field: str) -> int:
    if raw in (None, ""):
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise ValidationError({field: "must be an integer"})
    return max(minimum, min(maximum, value))


@dataclass(frozen=True)
class ListFindingsRequest:
    workspace_id: UUID
    severity: str | None
    status: str | None
    source: str | None
    asset_urn: str | None
    order_by: str
    limit: int
    offset: int

    @classmethod
    def from_request(cls, request, workspace_id) -> ListFindingsRequest:
        qp = request.query_params
        return cls(
            workspace_id=workspace_id,
            severity=_valid_choice(qp.get("severity"), {s.value for s in Severity}, "severity"),
            status=_valid_choice(qp.get("status"), {s.value for s in FindingStatus}, "status"),
            source=(qp.get("source") or "").strip() or None,
            asset_urn=(qp.get("asset_urn") or "").strip() or None,
            order_by=_valid_choice(qp.get("order_by"), _ORDER_BY_CHOICES, "order_by") or _DEFAULT_ORDER,
            limit=_int_param(qp.get("limit"), default=DEFAULT_LIMIT, minimum=1, maximum=MAX_LIMIT, field="limit"),
            offset=_int_param(qp.get("offset"), default=0, minimum=0, maximum=10_000_000, field="offset"),
        )

    def to_query(self) -> ListFindingsQuery:
        return ListFindingsQuery(
            workspace_id=self.workspace_id,
            severity=self.severity,
            status=self.status,
            source=self.source,
            asset_urn=self.asset_urn,
            order_by=self.order_by,
            limit=self.limit,
            offset=self.offset,
        )
