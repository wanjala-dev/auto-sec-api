"""Generic scan orchestration — ONE task drives every pillar.

``run_scan`` resolves the registered ``ScannerPort`` for a ``source``, vends
short-lived read-only credentials when the target needs them (ECR), reports live
progress through the shared background-job reporter, and hands off to the DRY
``run_scan_and_ingest`` choreography. ``dispatch_scan`` sends the task to the
pillar's own hardened queue (``apply_async(queue=...)`` — dynamic per source), so
each engine runs only on the isolated worker that carries its binary.

Adding a pillar needs no new task: register the adapter + queue and dispatch here.
"""

from __future__ import annotations

import logging
from typing import Any

from celery import shared_task

logger = logging.getLogger(__name__)


def dispatch_scan(
    *,
    source: str,
    workspace_id: str,
    target_ref: str,
    connection_id: str | None = None,
    account_id: str = "",
    params: dict | None = None,
):
    """Enqueue a scan onto the pillar's isolated queue. Returns the AsyncResult."""
    from components.scanning.application.providers.scanner_registry import queue_for

    return run_scan.apply_async(
        kwargs={
            "source": source,
            "workspace_id": workspace_id,
            "target_ref": target_ref,
            "connection_id": connection_id,
            "account_id": account_id,
            "params": params or {},
        },
        queue=queue_for(source),
    )


@shared_task(
    name="scanning.run_scan",
    soft_time_limit=1800,
    time_limit=1860,
    max_retries=0,
)
def run_scan(
    *,
    source: str,
    workspace_id: str,
    target_ref: str,
    connection_id: str | None = None,
    account_id: str = "",
    params: dict | None = None,
) -> dict[str, Any]:
    """Run the scanner registered for *source* against *target_ref*; ingest to the SSOT."""
    from components.scanning.application.providers.scanner_registry import (
        UnknownScannerError,
        get_scanner,
    )
    from components.scanning.infrastructure.services.run_scan_service import run_scan_and_ingest
    from components.shared_kernel.application.ports.scanner_port import ScanTarget
    from components.shared_platform.application.providers.job_progress_provider import (
        complete_job,
        fail_job,
        start_job,
        update_job,
    )

    try:
        scanner = get_scanner(source)
    except UnknownScannerError:
        logger.error("run_scan unknown_source source=%s", source)
        return {"success": False, "error": "unknown_source"}

    job_id = start_job(
        workspace_id=workspace_id,
        job_type="security_scan",
        title=f"{source} · {target_ref}",
        phase="starting",
        detail=f"Scanning {target_ref}",
    )

    try:
        credentials = _vend_credentials(connection_id=connection_id, account_id=account_id)
        update_job(job_id=job_id, progress=15, phase="scanning", detail=f"Running {source}")

        last = {"pct": 15}

        def _on_progress(pct: float) -> None:
            mapped = 15 + int(max(0.0, min(100.0, pct)) * 0.8)
            if mapped > last["pct"]:
                last["pct"] = mapped
                update_job(job_id=job_id, progress=mapped, phase="scanning", detail=f"{target_ref} — {int(pct)}%")

        run = run_scan_and_ingest(
            workspace_id=workspace_id,
            source=source,
            target=ScanTarget(identifier=target_ref, credentials=credentials, params=params or {}),
            scanner=scanner,
            connection_id=connection_id,
            account_id=account_id,
            on_progress=_on_progress,
        )
    except Exception:
        logger.exception("run_scan failed source=%s target=%s", source, target_ref)
        fail_job(job_id=job_id, error="scan_failed")
        return {"success": False, "error": "scan_failed"}

    complete_job(
        job_id=job_id,
        resource_id=str(run.id),
        detail=f"{run.failed_count} findings",
    )
    return {"success": True, "run_id": str(run.id), "findings": run.failed_count}


def _vend_credentials(*, connection_id: str | None, account_id: str) -> dict | None:
    """Assume the customer's read-only role for registry access, or ``None`` for a
    public target. The single AWS token-vending seam — never a scan-local assume-role."""
    if not connection_id:
        return None
    from components.integrations.application.providers.aws_credentials_provider import (
        get_aws_credentials_port,
    )
    from infrastructure.persistence.integrations.models import AwsOrganizationConnection

    connection = AwsOrganizationConnection.objects.filter(id=connection_id).first()
    if connection is None:
        return None
    return get_aws_credentials_port().assume_role(
        account_id=account_id or connection.management_account_id,
        role_name=connection.role_name,
        external_id=connection.external_id,
        session_name="autosec-scan",
    )
