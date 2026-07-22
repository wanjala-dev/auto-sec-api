"""Output DTOs for the report API."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from components.report.domain.report_kind import registered_kinds


def _iso(value) -> str | None:
    return value.isoformat() if value is not None else None


class ReportResource:
    """One report row → API dict (list + detail + status)."""

    @staticmethod
    def from_dict(report: Mapping[str, Any]) -> dict[str, Any]:
        assembled = report.get("assembled") or {}
        narrative = assembled.get("narrative") or {}
        return {
            "id": report["id"],
            "workspace_id": report["workspace_id"],
            "kind": report["kind"],
            "title": report["title"],
            "status": report["status"],
            "scope": report.get("scope") or {},
            "finding_count": report.get("finding_count", 0),
            "error_message": report.get("error_message") or "",
            # Download is only offered once approved (gate is enforced server-side).
            "downloadable": report["status"] == "approved",
            "narrative_faithful": bool(narrative.get("faithful", True)) if narrative else True,
            "pdf_generated_at": _iso(report.get("pdf_generated_at")),
            "approved_at": _iso(report.get("approved_at")),
            "approved_by_id": report.get("approved_by_id"),
            "created_at": _iso(report.get("created_at")),
            "updated_at": _iso(report.get("updated_at")),
        }

    @staticmethod
    def collection(reports) -> list[dict[str, Any]]:
        return [ReportResource.from_dict(r) for r in reports]


class ReportKindResource:
    """The kind picker payload — every registered kind (only pentest enabled
    today, rendered as a picker so a future kind appears with no FE change)."""

    @staticmethod
    def collection() -> list[dict[str, Any]]:
        return [{"id": spec.id, "title": spec.title, "enabled": True} for spec in registered_kinds()]
