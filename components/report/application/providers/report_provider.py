"""Composition root for the report context — wires ports to adapters.

Policy decision (which adapter implements which port) lives in the application
layer, not infrastructure. Every use case + service the controller and the
Celery task need is built here.
"""

from __future__ import annotations


class ReportProvider:
    @staticmethod
    def repository():
        from components.report.infrastructure.repositories.report_repository import OrmReportRepository

        return OrmReportRepository()

    @staticmethod
    def finding_source():
        from components.report.infrastructure.repositories.board_finding_repository import (
            BoardFindingRepository,
        )

        return BoardFindingRepository()

    @staticmethod
    def storage():
        from components.report.infrastructure.services.report_pdf_storage_service import (
            ReportPdfStorageService,
        )

        return ReportPdfStorageService()

    @staticmethod
    def narrative():
        from components.report.infrastructure.adapters.grounded_report_narrative_adapter import (
            GroundedReportNarrativeAdapter,
        )

        return GroundedReportNarrativeAdapter()

    @staticmethod
    def renderer():
        from components.report.infrastructure.adapters.gotenberg_report_pdf_renderer import (
            GotenbergReportPdfRenderer,
        )

        return GotenbergReportPdfRenderer()

    @staticmethod
    def workspace_identity():
        from components.report.infrastructure.adapters.orm_workspace_identity_adapter import (
            OrmWorkspaceIdentityAdapter,
        )

        return OrmWorkspaceIdentityAdapter()

    @classmethod
    def build_generate_report_use_case(cls):
        from components.report.application.use_cases.generate_report_use_case import (
            GenerateReportUseCase,
        )

        return GenerateReportUseCase(
            reports=cls.repository(),
            finding_source=cls.finding_source(),
            narrative=cls.narrative(),
            renderer=cls.renderer(),
            storage=cls.storage(),
            workspace_identity=cls.workspace_identity(),
        )

    @classmethod
    def build_assembler(cls):
        from components.report.application.services.report_assembler_service import (
            ReportAssemblerService,
        )

        return ReportAssemblerService(cls.finding_source())
