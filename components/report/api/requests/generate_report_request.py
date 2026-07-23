"""Input DTO for POST /report/generate/."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from components.report.domain.report_kind import get_report_kind


@dataclass(frozen=True)
class GenerateReportRequest:
    workspace_id: str
    kind: str
    title: str
    scope: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_request(cls, *, workspace_id: str, data: dict[str, Any]) -> GenerateReportRequest:
        data = data or {}
        kind = str(data.get("kind") or "pentest").strip()
        spec = get_report_kind(kind)  # raises UnknownReportKind on a bad kind
        title = str(data.get("title") or "").strip() or spec.title

        raw_scope = data.get("scope") or {}
        scope: dict[str, Any] = {
            "client_name": str(raw_scope.get("client_name") or "").strip(),
            "engagement_title": str(raw_scope.get("engagement_title") or title).strip(),
            "scope_summary": str(raw_scope.get("scope_summary") or "").strip(),
            "target": str(raw_scope.get("target") or "").strip(),
            "approach": str(raw_scope.get("approach") or "").strip(),
        }
        source_types = raw_scope.get("source_types")
        if isinstance(source_types, list) and source_types:
            scope["source_types"] = [str(s) for s in source_types]
        for key in ("since", "until"):
            if raw_scope.get(key):
                scope[key] = str(raw_scope[key])
        if raw_scope.get("limit"):
            scope["limit"] = int(raw_scope["limit"])

        return cls(workspace_id=workspace_id, kind=kind, title=title, scope=scope)
