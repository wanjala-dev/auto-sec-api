"""Celery orchestration for the nightly Prowler CSPM scan.

``schedule_prowler_runs`` (beat) fans out one ``run_prowler_scan_for_account``
per verified account of every CONNECTED connection whose workspace has opted in
(``feature.cloud_posture``). Each child assumes the account's read-only role
via the integrations credential-vending port (the single AWS token-vending
seam — never a scan-local assume-role), runs Prowler, and ingests the OCSF
result as a ``CloudPostureScan``.

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


@shared_task(name="cloud_posture.run_prowler_scan_for_account", soft_time_limit=1800, time_limit=1860)
def run_prowler_scan_for_account(connection_id: str, account_id: str) -> dict[str, Any]:
    """Assume the account role, run Prowler, ingest the result as a scan."""
    from infrastructure.persistence.integrations.models import AwsOrganizationConnection

    connection = AwsOrganizationConnection.objects.filter(id=connection_id).first()
    if connection is None:
        logger.warning("cloud_posture_scan connection_not_found id=%s", connection_id)
        return {"success": False, "error": "connection_not_found"}

    try:
        credentials = get_aws_credentials_port().assume_role(
            account_id=account_id,
            role_name=connection.role_name,
            external_id=connection.external_id,
            session_name="autosec-prowler",
        )
        records = run_prowler(credentials=credentials, account_id=account_id, regions=list(connection.regions or []))
    except Exception:
        logger.exception("cloud_posture_scan failed connection=%s account=%s", connection_id, account_id)
        return {"success": False, "error": "scan_failed"}

    scan = ingest_prowler_scan(
        workspace_id=connection.workspace_id,
        account_id=account_id,
        records=records,
        connection_id=connection.id,
        engine_version="prowler",
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
    """Fan-out beat entry: enqueue a scan per verified account of opted-in orgs."""
    from components.shared_platform.application.providers.feature_flags_provider import (
        get_feature_flags_provider,
    )
    from infrastructure.persistence.integrations.models import (
        AwsAccountLink,
        AwsOrganizationConnection,
    )

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

        account_ids = AwsAccountLink.objects.filter(
            connection_id=connection.id, status=AwsAccountLink.Status.VERIFIED
        ).values_list("account_id", flat=True)
        for account_id in account_ids:
            run_prowler_scan_for_account.delay(str(connection.id), account_id)
            scheduled += 1

    logger.info("schedule_cloud_posture_scans scheduled=%d", scheduled)
    return {"success": True, "scheduled": scheduled}
