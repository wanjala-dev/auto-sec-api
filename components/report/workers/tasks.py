"""Celery entry point for report generation — a PRIMARY ADAPTER.

Thin wrapper: takes the report id (never an object), delegates to the generate
use case. Idempotent-ish — a re-run re-assembles + overwrites the same S3 key.
All ORM access is lazy inside the use case's adapters, so this module is safe to
eager-import from ``api/celery.py`` (it imports no models at module level).
"""

from __future__ import annotations

import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(
    name="report.generate_report",
    bind=True,
    max_retries=3,
    default_retry_delay=30,
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    time_limit=600,
    soft_time_limit=540,
)
def generate_report(self, report_id: str, workspace_id: str) -> dict:
    logger.info(
        "report.generate_report started report_id=%s workspace_id=%s task_id=%s",
        report_id,
        workspace_id,
        self.request.id,
    )
    from components.report.application.providers.report_provider import ReportProvider
    from components.report.application.use_cases.generate_report_use_case import (
        GenerateReportCommand,
    )

    use_case = ReportProvider.build_generate_report_use_case()
    use_case.execute(GenerateReportCommand(report_id=report_id, workspace_id=workspace_id))
    logger.info(
        "report.generate_report completed report_id=%s task_id=%s",
        report_id,
        self.request.id,
    )
    return {"report_id": report_id, "status": "ok"}
