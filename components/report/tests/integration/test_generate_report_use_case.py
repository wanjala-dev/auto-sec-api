"""Integration test: the generate use case, end to end, DB-backed.

The finding source is a fake (deterministic findings), the narrative is a fake
grounded writer, the renderer is stubbed at the PDF-bytes boundary (never a real
Gotenberg call), and the storage records the bytes it was handed. The real
repository + real Report ORM row + real assembler + real HTML builder run.
Proves: draft → generated, a Report row carrying the assembled data, the PDF
bytes captured, and a failure flips the row to failed.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from components.report.application.use_cases.generate_report_use_case import (
    GenerateReportCommand,
    GenerateReportUseCase,
)
from components.report.domain.entities.assembled_report_entity import ReportNarrative
from components.report.infrastructure.repositories.report_repository import OrmReportRepository

pytestmark = pytest.mark.django_db


# ── fakes ────────────────────────────────────────────────────────────────
class FakeFindingSource:
    def __init__(self, findings):
        self._findings = findings

    def list_findings(self, query):
        from components.report.application.ports.finding_source_port import FindingPage

        return FindingPage(findings=tuple(self._findings), total_matched=len(self._findings))


class FakeNarrative:
    def write(self, *, assembled, workspace_name, engagement_title, scope_summary):
        return ReportNarrative(
            executive_summary=f"{assembled.histogram.total} finding(s) identified.",
            overall_assessment="Themes reviewed.",
            faithful=True,
        )


class StubRenderer:
    """Stubs the PDF-bytes boundary — NEVER calls a real Gotenberg."""

    def __init__(self):
        self.last_html = None

    def render(self, *, html, log_context=None):
        self.last_html = html
        return b"%PDF-1.7 fake report bytes"


class RecordingStorage:
    def __init__(self):
        self.stored = {}

    def object_key(self, *, workspace_id, report_id):
        return f"{workspace_id}/{report_id}.pdf"

    def put_pdf(self, *, key, body):
        self.stored[key] = body


class FakeIdentity:
    def get(self, *, workspace_id):
        from components.report.application.ports.workspace_identity_port import WorkspaceIdentity

        return WorkspaceIdentity(workspace_id=workspace_id, name="Acme SOC", logo_url="")


def _finding(severity="high", title="Auth failures"):
    return {
        "id": "task-1",
        "title": title,
        "description": "",
        "severity": severity,
        "source": "logwatch.error",
        "source_type": "ai.log_watch.error",
        "status": "open",
        "created_at": datetime(2026, 7, 20, 12, 0, 0),
        "is_sample": False,
        "triage": {"on_board": False},
        "metadata": {
            "severity": severity,
            "action_type": "log_watch.error",
            "ai_headline": title,
            "ai_narrative": "Detector narrative.",
            "payload": {
                "signal": "repeated failures",
                "service": "auth-svc",
                "level": "ERROR",
                "evidence": [{"type": "log_line", "detail": "401 x 42"}],
                "recommendation": "Rate-limit login.",
            },
        },
    }


def _use_case(findings, *, renderer=None, storage=None, narrative=None):
    return GenerateReportUseCase(
        reports=OrmReportRepository(),
        finding_source=FakeFindingSource(findings),
        narrative=narrative or FakeNarrative(),
        renderer=renderer or StubRenderer(),
        storage=storage or RecordingStorage(),
        workspace_identity=FakeIdentity(),
    )


def _make_report(workspace_factory):
    from infrastructure.persistence.report.models import Report

    ws = workspace_factory()
    report = Report.objects.create(workspace=ws, kind="pentest", title="Acme Pentest", status=Report.Status.DRAFT)
    return report, str(ws.id)


class TestGenerateReportUseCase:
    def test_generates_and_stores_pdf(self, workspace_factory):
        from infrastructure.persistence.report.models import Report

        report, ws_id = _make_report(workspace_factory)
        renderer, storage = StubRenderer(), RecordingStorage()
        uc = _use_case([_finding()], renderer=renderer, storage=storage)

        uc.execute(GenerateReportCommand(report_id=str(report.id), workspace_id=ws_id))

        report.refresh_from_db()
        assert report.status == Report.Status.GENERATED
        assert report.finding_count == 1
        assert report.pdf_key == f"{ws_id}/{report.id}.pdf"
        assert report.pdf_generated_at is not None
        # PDF bytes captured, non-empty.
        assert storage.stored[report.pdf_key] == b"%PDF-1.7 fake report bytes"
        assert len(storage.stored[report.pdf_key]) > 0
        # Assembled ground truth persisted.
        assert report.assembled["histogram"]["high"] == 1
        assert report.assembled["technical_findings"][0]["fid"] == "F-01"
        # The rendered HTML carried the finding + org name.
        assert "Acme SOC" in renderer.last_html
        assert "Auth failures" in renderer.last_html

    def test_empty_board_still_generates(self, workspace_factory):
        from infrastructure.persistence.report.models import Report

        report, ws_id = _make_report(workspace_factory)
        uc = _use_case([])
        uc.execute(GenerateReportCommand(report_id=str(report.id), workspace_id=ws_id))
        report.refresh_from_db()
        assert report.status == Report.Status.GENERATED
        assert report.finding_count == 0

    def test_render_failure_marks_report_failed(self, workspace_factory):
        from infrastructure.persistence.report.models import Report

        report, ws_id = _make_report(workspace_factory)

        class BoomRenderer:
            def render(self, *, html, log_context=None):
                raise RuntimeError("gotenberg down")

        uc = _use_case([_finding()], renderer=BoomRenderer())
        with pytest.raises(RuntimeError):
            uc.execute(GenerateReportCommand(report_id=str(report.id), workspace_id=ws_id))

        report.refresh_from_db()
        assert report.status == Report.Status.FAILED
        assert "gotenberg down" in report.error_message


class TestTheGeneratedDocumentIsHonest:
    """End to end against the REAL SSOT adapter — the proof that the change
    reaches the rendered deliverable, not just the port."""

    def _ssot_use_case(self, renderer):
        from components.report.infrastructure.repositories.ssot_finding_repository import (
            SsotFindingRepository,
        )

        return GenerateReportUseCase(
            reports=OrmReportRepository(),
            finding_source=SsotFindingRepository(),
            narrative=FakeNarrative(),
            renderer=renderer,
            storage=RecordingStorage(),
            workspace_identity=FakeIdentity(),
        )

    def _finding(self, ws, **overrides):
        import uuid

        from django.utils import timezone

        from infrastructure.persistence.findings.models import Finding

        now = timezone.now()
        return Finding.objects.create(
            workspace=ws,
            source=overrides.pop("source", "cloud_posture.prowler"),
            fingerprint=f"fp-{uuid.uuid4()}",
            asset_urn=overrides.pop("asset_urn", f"arn:aws:s3:::b-{uuid.uuid4()}"),
            severity=overrides.pop("severity", "medium"),
            status=overrides.pop("status", "open"),
            title=overrides.pop("title", "CloudTrail is not multi-region"),
            description="API activity in secondary regions is invisible.",
            remediation="Enable a multi-region trail.",
            first_seen_at=now,
            last_seen_at=now,
            **overrides,
        )

    def test_a_medium_finding_reaches_the_rendered_report(self, workspace_factory):
        from infrastructure.persistence.report.models import Report

        report, ws_id = _make_report(workspace_factory)
        ws = report.workspace
        self._finding(ws, severity="medium", title="CloudTrail is not multi-region")

        renderer = StubRenderer()
        self._ssot_use_case(renderer).execute(
            GenerateReportCommand(report_id=str(report.id), workspace_id=ws_id)
        )

        report.refresh_from_db()
        assert report.status == Report.Status.GENERATED
        assert report.finding_count == 1
        assert report.assembled["histogram"]["medium"] == 1
        # It is IN THE DOCUMENT, not merely in the assembled JSON.
        assert "CloudTrail is not multi-region" in renderer.last_html
        # …and marked untriaged, because it never reached the board.
        assert "Untriaged" in renderer.last_html

    def test_sample_data_is_stamped_on_the_document(self, workspace_factory):
        report, ws_id = _make_report(workspace_factory)
        self._finding(report.workspace, source="sample.cloud_posture", severity="critical", title="Demo bucket")

        renderer = StubRenderer()
        self._ssot_use_case(renderer).execute(
            GenerateReportCommand(report_id=str(report.id), workspace_id=ws_id)
        )

        report.refresh_from_db()
        assert report.assembled["sample_finding_count"] == 1
        assert "Contains sample data" in renderer.last_html
        assert "SAMPLE DATA" in renderer.last_html.upper()
        assert "Sample</span>" in renderer.last_html, "each sample finding carries its own marker"

    def test_truncation_is_stated_on_the_document(self, workspace_factory):
        report, ws_id = _make_report(workspace_factory)
        ws = report.workspace
        report.scope = {"limit": 2}
        report.save(update_fields=["scope"])
        for band in ("critical", "high", "medium", "low"):
            self._finding(ws, severity=band, title=f"{band} finding")

        renderer = StubRenderer()
        self._ssot_use_case(renderer).execute(
            GenerateReportCommand(report_id=str(report.id), workspace_id=ws_id)
        )

        report.refresh_from_db()
        assert report.assembled["total_matched"] == 4
        assert report.assembled["truncated_count"] == 2
        assert "could not be included" in renderer.last_html
        assert "4 findings matched" in renderer.last_html

    def test_suppressed_and_resolved_counts_are_stated_not_hidden(self, workspace_factory):
        from django.utils import timezone

        report, ws_id = _make_report(workspace_factory)
        ws = report.workspace
        self._finding(ws, severity="high", title="Open one")
        self._finding(ws, severity="high", title="Accepted", status="suppressed")
        self._finding(ws, severity="high", title="Fixed", status="resolved", resolved_at=timezone.now())

        renderer = StubRenderer()
        self._ssot_use_case(renderer).execute(
            GenerateReportCommand(report_id=str(report.id), workspace_id=ws_id)
        )

        report.refresh_from_db()
        assert report.assembled["excluded_suppressed"] == 1
        assert report.assembled["excluded_resolved"] == 1
        assert "suppressed as accepted risk" in renderer.last_html
        assert "resolved during the period" in renderer.last_html
        assert "Accepted" not in renderer.last_html.split("Findings Matrix")[-1].split("Appendix")[0]
