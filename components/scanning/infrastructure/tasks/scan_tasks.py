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
    trigger: str = "manual",
    triggered_by: str | None = None,
    params: dict | None = None,
):
    """Enqueue a scan onto the pillar's isolated queue. Returns the AsyncResult.

    ``trigger`` / ``triggered_by`` are the provenance the run row records: the
    coarse origin ("manual" / "schedule") and, for manual runs, the operator's
    user id.
    """
    from components.scanning.application.providers.scanner_registry import queue_for

    return run_scan.apply_async(
        kwargs={
            "source": source,
            "workspace_id": workspace_id,
            "target_ref": target_ref,
            "connection_id": connection_id,
            "account_id": account_id,
            "trigger": trigger,
            "triggered_by": triggered_by,
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
    trigger: str = "manual",
    triggered_by: str | None = None,
    params: dict | None = None,
) -> dict[str, Any]:
    """Run the scanner registered for *source* against *target_ref*; ingest to the SSOT."""
    from components.scanning.application.providers.scanner_registry import (
        UnknownScannerError,
        credentials_vendor_for,
        get_scanner,
        post_ingest_for,
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
        # Per-source credential vend (registry seam) — e.g. code_security vends a VCS
        # read token through the ADR 0010 connection; pillars without a vendor use
        # the default AWS assume-role path below.
        vendor = credentials_vendor_for(source)
        if vendor is not None:
            credentials = vendor(
                workspace_id=workspace_id,
                target_ref=target_ref,
                connection_id=connection_id,
                account_id=account_id,
                params=params or {},
            )
        else:
            credentials = _vend_credentials(connection_id=connection_id, account_id=account_id)
        update_job(job_id=job_id, progress=15, phase="scanning", detail=f"Running {source}")

        last = {"pct": 15}

        def _on_progress(pct: float) -> None:
            mapped = 15 + int(max(0.0, min(100.0, pct)) * 0.8)
            if mapped > last["pct"]:
                last["pct"] = mapped
                update_job(job_id=job_id, progress=mapped, phase="scanning", detail=f"{target_ref} — {int(pct)}%")

        # The pillar's optional post-ingest hook (e.g. container_security persisting
        # the image SBOM). Adapted here from ORM run → primitives so the pillar's
        # APPLICATION hook stays framework-free. Best-effort by policy (see
        # run_scan_and_ingest) — never fails a completed scan.
        post_ingest = post_ingest_for(source)
        on_completed = None
        if post_ingest is not None:

            def on_completed(run, result, _hook=post_ingest):
                _hook(
                    run_id=run.id,
                    workspace_id=run.workspace_id,
                    target_ref=run.target_ref,
                    result=result,
                )

        run = run_scan_and_ingest(
            workspace_id=workspace_id,
            source=source,
            target=ScanTarget(identifier=target_ref, credentials=credentials, params=params or {}),
            scanner=scanner,
            connection_id=connection_id,
            account_id=account_id,
            trigger=trigger,
            triggered_by=triggered_by,
            on_progress=_on_progress,
            on_completed=on_completed,
        )
    except Exception:
        logger.exception("run_scan failed source=%s target=%s", source, target_ref)
        _release_dispatch_lock(workspace_id=workspace_id, source=source, target_ref=target_ref)
        fail_job(job_id=job_id, error="scan_failed")
        _publish_scan_failed(
            workspace_id=workspace_id,
            source=source,
            run_id=str(job_id or ""),
            target_ref=target_ref,
            account_id=account_id,
        )
        return {"success": False, "error": "scan_failed"}

    complete_job(
        job_id=job_id,
        resource_id=str(run.id),
        detail=f"{run.failed_count} findings",
    )
    return {"success": True, "run_id": str(run.id), "findings": run.failed_count}


def _release_dispatch_lock(*, workspace_id, source: str, target_ref: str) -> None:
    """Free the anti-spam dispatch lock on a FAILED run — a transient engine
    failure must not cooldown-lock the target (the gate's contract). Loss-tolerant."""
    try:
        from components.scanning.application.providers.scan_gate_provider import (
            release_dispatch_lock,
        )

        release_dispatch_lock(workspace_id=workspace_id, source=source, target_ref=target_ref)
    except Exception:
        logger.exception("run_scan_lock_release_failed source=%s target=%s", source, target_ref)


def _publish_scan_failed(*, workspace_id, source: str, run_id: str, target_ref: str, account_id: str) -> None:
    """Emit ``ScanFailed`` so the funnel can alert that coverage is degraded (ADR 0016).

    Loss-tolerant: the alert must never change the task's failure handling or its
    return contract. ``reason`` stays a coarse token — a raw exception string could
    carry internal paths/ARNs into a third-party chat channel.
    """
    try:
        from uuid import UUID

        from components.shared_kernel.domain.events import ScanFailed
        from components.shared_kernel.infrastructure.adapters.celery_event_publisher import (
            CeleryEventPublisher,
        )

        CeleryEventPublisher().publish(
            ScanFailed(
                workspace_id=UUID(str(workspace_id)),
                source=source,
                engine=source.rsplit(".", 1)[-1],
                run_id=run_id,
                target_ref=str(target_ref or "")[:512],
                account_id=str(account_id or ""),
                reason="scan engine failure",
            )
        )
    except Exception:
        logger.exception("run_scan_failed_event_publish_failed source=%s target=%s", source, target_ref)


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
