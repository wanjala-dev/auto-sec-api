"""ORM adapter for :class:`ReportRepositoryPort`."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from django.utils import timezone

from components.report.application.ports.report_repository_port import ReportRepositoryPort


def _to_dict(report) -> dict[str, Any]:
    return {
        "id": str(report.id),
        "workspace_id": str(report.workspace_id),
        "kind": report.kind,
        "title": report.title,
        "status": report.status,
        "scope": report.scope or {},
        "assembled": report.assembled or {},
        "finding_count": report.finding_count,
        "error_message": report.error_message or "",
        "pdf_key": report.pdf_key or "",
        "pdf_generated_at": report.pdf_generated_at,
        "approved_by_id": str(report.approved_by_id) if report.approved_by_id else None,
        "approved_at": report.approved_at,
        "created_by_id": str(report.created_by_id) if report.created_by_id else None,
        "created_at": report.created_at,
        "updated_at": report.updated_at,
    }


class OrmReportRepository(ReportRepositoryPort):
    def create(
        self,
        *,
        workspace_id: str,
        kind: str,
        title: str,
        scope: Mapping[str, Any],
        created_by_id: str | None,
    ) -> Mapping[str, Any]:
        from infrastructure.persistence.report.models import Report

        report = Report.objects.create(
            workspace_id=workspace_id,
            kind=kind,
            title=title,
            scope=dict(scope or {}),
            created_by_id=created_by_id,
            status=Report.Status.DRAFT,
        )
        return _to_dict(report)

    def get(self, *, report_id: str, workspace_id: str) -> Mapping[str, Any] | None:
        from infrastructure.persistence.report.models import Report

        report = Report.objects.filter(id=report_id, workspace_id=workspace_id).first()
        return _to_dict(report) if report is not None else None

    def list(self, *, workspace_id: str, kind: str | None = None) -> list[Mapping[str, Any]]:
        from infrastructure.persistence.report.models import Report

        qs = Report.objects.filter(workspace_id=workspace_id)
        if kind:
            qs = qs.filter(kind=kind)
        return [_to_dict(r) for r in qs.order_by("-created_at")]

    def mark_generating(self, *, report_id: str) -> None:
        from infrastructure.persistence.report.models import Report

        Report.objects.filter(id=report_id).update(
            status=Report.Status.GENERATING, error_message="", updated_at=timezone.now()
        )

    def mark_generated(
        self,
        *,
        report_id: str,
        assembled: Mapping[str, Any],
        finding_count: int,
        pdf_key: str,
    ) -> None:
        from infrastructure.persistence.report.models import Report

        Report.objects.filter(id=report_id).update(
            status=Report.Status.GENERATED,
            assembled=dict(assembled or {}),
            finding_count=finding_count,
            pdf_key=pdf_key,
            pdf_generated_at=timezone.now(),
            error_message="",
            updated_at=timezone.now(),
        )

    def mark_failed(self, *, report_id: str, error_message: str) -> None:
        from infrastructure.persistence.report.models import Report

        Report.objects.filter(id=report_id).update(
            status=Report.Status.FAILED,
            error_message=(error_message or "")[:4000],
            updated_at=timezone.now(),
        )

    def mark_approved(self, *, report_id: str, approved_by_id: str) -> Mapping[str, Any]:
        from infrastructure.persistence.report.models import Report

        now = timezone.now()
        Report.objects.filter(id=report_id).update(
            status=Report.Status.APPROVED,
            approved_by_id=approved_by_id,
            approved_at=now,
            updated_at=now,
        )
        report = Report.objects.filter(id=report_id).first()
        return _to_dict(report)
