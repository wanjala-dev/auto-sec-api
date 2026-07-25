"""Celery orchestration for the Prowler CSPM scan.

``schedule_prowler_runs`` (beat) fans out one ``run_prowler_scan_for_account``
per scannable account of every CONNECTED connection whose workspace has opted in
(``feature.cloud_posture``); the on-demand "Scan now" endpoint reuses the same
per-connection fan-out (``enqueue_connection_scans``) so both paths are byte-for
-byte identical. Each child assumes the account's read-only role via the
integrations credential-vending port (the single AWS token-vending seam — never
a scan-local assume-role), runs Prowler, and ingests the OCSF result as a
``CloudPostureScan``.

The scan attempt IS the per-account role verification: a successful ingest
promotes the account link to VERIFIED, an assume/scan failure marks it FAILED
(degrading that one account without blocking the rest of the org).

The live path needs the operator IAM audit-role rollout + a Prowler install; the
two seams (``get_aws_credentials_port`` / ``run_prowler``) are mocked in tests.
"""

from __future__ import annotations

import logging
from typing import Any

from celery import shared_task

from components.cloud_posture.infrastructure.adapters.prowler_runner import run_prowler
from components.cloud_posture.infrastructure.services.prowler_ingest_service import (
    ingest_prowler_scan,
)
from components.integrations.application.providers.aws_credentials_provider import (
    get_aws_credentials_port,
)

logger = logging.getLogger(__name__)


def _set_link_status(connection_id, account_id: str, status: str) -> None:
    """Best-effort update of an account link's verification status (no-op if absent)."""
    from infrastructure.persistence.integrations.models import AwsAccountLink

    AwsAccountLink.objects.filter(connection_id=connection_id, account_id=account_id).update(status=status)


def enqueue_connection_scans(connection) -> int:
    """Enqueue one async scan per scannable account link of a connection.

    Shared by the beat scheduler and the on-demand endpoint. Skips terminal
    links (FAILED / SUSPENDED / EXCLUDED); DISCOVERED + VERIFIED are scanned —
    the scan re-verifies each account on every run.
    """
    from infrastructure.persistence.integrations.models import AwsAccountLink

    terminal = [
        AwsAccountLink.Status.FAILED,
        AwsAccountLink.Status.SUSPENDED,
        AwsAccountLink.Status.EXCLUDED,
    ]
    account_ids = (
        AwsAccountLink.objects.filter(connection_id=connection.id)
        .exclude(status__in=terminal)
        .values_list("account_id", flat=True)
    )
    enqueued = 0
    for account_id in account_ids:
        run_prowler_scan_for_account.delay(str(connection.id), account_id)
        enqueued += 1
    return enqueued


def enqueue_scan_for_connection(*, workspace_id, connection_id) -> int | None:
    """Load a workspace's connection and enqueue its scans (on-demand entry).

    Returns the number of scans enqueued, or ``None`` if no such connection
    belongs to the workspace (the endpoint maps that to 404).
    """
    from infrastructure.persistence.integrations.models import AwsOrganizationConnection

    connection = AwsOrganizationConnection.objects.filter(id=connection_id, workspace_id=workspace_id).first()
    if connection is None:
        return None
    return enqueue_connection_scans(connection)


@shared_task(
    name="cloud_posture.run_prowler_scan_for_account",
    # Pin to the dedicated queue: this task shells out to Prowler, which is ONLY
    # installed in the cloud-posture worker's isolated venv. The global route
    # table is inert (settings use the dead `CELERY_ROUTES` name, not
    # `CELERY_TASK_ROUTES`), so without this the task falls to the default queue
    # and dies with `FileNotFoundError: 'prowler'`. Queue name == CELERY_QUEUE_CLOUD_POSTURE.
    queue="cloud_posture",
    soft_time_limit=1800,
    time_limit=1860,
)
def run_prowler_scan_for_account(connection_id: str, account_id: str) -> dict[str, Any]:
    """Assume the account role, run Prowler, ingest the result; (re)verify the link."""
    from infrastructure.persistence.integrations.models import AwsAccountLink, AwsOrganizationConnection

    # Lazy import: the shared_platform services package __init__ eagerly pulls
    # in ORM models, so a module-level import here would run at Celery-app load
    # (before the app registry is ready). Import inside the task, as the model
    # imports in this file already do.
    from components.shared_platform.infrastructure.services.job_progress import (
        complete_job,
        fail_job,
        start_job,
        update_job,
    )

    connection = AwsOrganizationConnection.objects.filter(id=connection_id).first()
    if connection is None:
        logger.warning("cloud_posture_scan connection_not_found id=%s", connection_id)
        return {"success": False, "error": "connection_not_found"}

    # Surface this long run to the user via the generic background-job reporter —
    # the HUD renders its live progress ring off these phase transitions. (The
    # smooth per-check % lands when the runner moves to the Prowler SDK.)
    job_id = start_job(
        workspace_id=connection.workspace_id,
        job_type="cloud_posture_scan",
        title=f"CSPM scan · {account_id}",
        phase="assuming_role",
        detail="Assuming the account audit role",
    )

    try:
        credentials = get_aws_credentials_port().assume_role(
            account_id=account_id,
            role_name=connection.role_name,
            external_id=connection.external_id,
            session_name="autosec-prowler",
        )
        update_job(job_id=job_id, progress=15, phase="scanning", detail=f"Running Prowler on {account_id}")
        records = run_prowler(credentials=credentials, account_id=account_id, regions=list(connection.regions or []))
        update_job(job_id=job_id, progress=90, phase="ingesting", detail="Persisting findings")
    except Exception:
        logger.exception("cloud_posture_scan failed connection=%s account=%s", connection_id, account_id)
        _set_link_status(connection_id, account_id, AwsAccountLink.Status.FAILED)
        fail_job(job_id=job_id, error="scan_failed")
        return {"success": False, "error": "scan_failed"}

    scan = ingest_prowler_scan(
        workspace_id=connection.workspace_id,
        account_id=account_id,
        records=records,
        connection_id=connection.id,
        engine_version="prowler",
    )
    # The scan proved the role in this account — promote the link to VERIFIED.
    _set_link_status(connection_id, account_id, AwsAccountLink.Status.VERIFIED)
    complete_job(
        job_id=job_id,
        resource_id=str(scan.id),
        detail=f"{scan.failed_count} findings across {scan.total_checks} checks",
    )
    logger.info(
        "cloud_posture_scan ingested connection=%s account=%s checks=%s failed=%s",
        connection_id,
        account_id,
        scan.total_checks,
        scan.failed_count,
    )
    return {"success": True, "scan_id": str(scan.id), "checks": scan.total_checks, "failed": scan.failed_count}


@shared_task(name="cloud_posture.schedule_prowler_runs", soft_time_limit=240, time_limit=300)
def schedule_prowler_runs() -> dict[str, Any]:
    """Fan-out beat entry: enqueue scans for every scannable account of opted-in orgs."""
    from components.shared_platform.application.providers.feature_flags_provider import (
        get_feature_flags_provider,
    )
    from infrastructure.persistence.integrations.models import AwsOrganizationConnection

    flags = get_feature_flags_provider()
    scheduled = 0

    connections = AwsOrganizationConnection.objects.filter(status=AwsOrganizationConnection.Status.CONNECTED).only(
        "id", "workspace", "role_name", "external_id", "regions"
    )

    for connection in connections.iterator():
        try:
            if not flags.is_feature_enabled("feature.cloud_posture", workspace_id=connection.workspace_id):
                continue
        except Exception:
            logger.exception("cloud_posture flag check failed workspace=%s", connection.workspace_id)
            continue
        scheduled += enqueue_connection_scans(connection)

    logger.info("schedule_cloud_posture_scans scheduled=%d", scheduled)
    return {"success": True, "scheduled": scheduled}
