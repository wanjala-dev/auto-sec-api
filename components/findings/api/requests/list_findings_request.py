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


def _parse_tag_groups(qp) -> tuple[tuple[str, ...], ...]:
    """Each ``tag=`` occurrence is an OR-group (comma-separated slugs); occurrences
    AND together (ADR 0015 D7 — the GitHub qualifier algebra)."""
    groups = []
    for raw_group in qp.getlist("tag"):
        slugs = tuple(s.strip() for s in (raw_group or "").split(",") if s.strip())
        if slugs:
            groups.append(slugs)
    return tuple(groups)


@dataclass(frozen=True)
class ListFindingsRequest:
    workspace_id: UUID
    severity: str | None
    status: str | None
    source: str | None
    asset_urn: str | None
    tag_slug_groups: tuple[tuple[str, ...], ...]
    exclude_tag_slugs: tuple[str, ...]
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
            tag_slug_groups=_parse_tag_groups(qp),
            exclude_tag_slugs=tuple(s.strip() for s in qp.getlist("exclude_tag") if s.strip()),
            order_by=_valid_choice(qp.get("order_by"), _ORDER_BY_CHOICES, "order_by") or _DEFAULT_ORDER,
            limit=_int_param(qp.get("limit"), default=DEFAULT_LIMIT, minimum=1, maximum=MAX_LIMIT, field="limit"),
            offset=_int_param(qp.get("offset"), default=0, minimum=0, maximum=10_000_000, field="offset"),
        )

    def to_query(self, *, tag_store=None) -> ListFindingsQuery:
        """Build the read query. Slug→id resolution happens HERE, once, through the
        tagging context's ``TagStorePort`` (ADR 0015 D7) — the findings port stays
        slug-agnostic. A group that resolves to zero live tags stays as an EMPTY
        group (⇒ zero results — strict, deterministic, GitHub-like); unknown
        ``exclude_tag`` slugs are no-ops.
        """
        tag_groups: tuple[tuple[UUID, ...], ...] = ()
        exclude_tag_ids: tuple[UUID, ...] = ()
        if tag_store is not None and self.tag_slug_groups:
            resolved_groups = []
            for group in self.tag_slug_groups:
                mapping = tag_store.resolve_slugs(self.workspace_id, group)
                resolved_groups.append(tuple(sorted(set(mapping.values()), key=str)))
            tag_groups = tuple(resolved_groups)
        if tag_store is not None and self.exclude_tag_slugs:
            mapping = tag_store.resolve_slugs(self.workspace_id, self.exclude_tag_slugs)
            exclude_tag_ids = tuple(sorted(set(mapping.values()), key=str))
        return ListFindingsQuery(
            workspace_id=self.workspace_id,
            severity=self.severity,
            status=self.status,
            source=self.source,
            asset_urn=self.asset_urn,
            tag_groups=tag_groups,
            exclude_tag_ids=exclude_tag_ids,
            order_by=self.order_by,
            limit=self.limit,
            offset=self.offset,
        )
