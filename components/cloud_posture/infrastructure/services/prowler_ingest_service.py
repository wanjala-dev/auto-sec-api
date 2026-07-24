"""Parse Prowler OCSF JSON and persist it as a cloud-posture snapshot.

Prowler (Apache-2.0) is the detection engine; this wraps its output. The parser
is pure (external JSON → domain entities) and engine-version-tolerant (defensive
field access); the ingest persists a ``CloudPostureScan`` + one
``CloudPostureFinding`` per actionable (non-PASS) check, deduped within the scan.

OCSF field paths (Prowler v4/v5): ``metadata.event_code`` (check id),
``status_code``, ``severity``, ``finding_info.{uid,title,desc}``,
``resources[].{uid,name,type,region,group.name}``, ``cloud.account.uid``,
``cloud.region``, ``unmapped.compliance``, ``remediation.desc``.
"""

from __future__ import annotations

import logging
from uuid import UUID

from django.utils import timezone

from components.cloud_posture.domain.entities.posture_finding_entity import NormalizedPostureFinding
from components.cloud_posture.domain.value_objects.enums import (
    CheckStatus,
    severity_from_prowler,
    status_from_prowler,
)

logger = logging.getLogger(__name__)


def _first_resource(record: dict) -> dict:
    resources = record.get("resources") or []
    first = resources[0] if resources else {}
    return first if isinstance(first, dict) else {}


def parse_prowler_ocsf(records: list[dict]) -> list[NormalizedPostureFinding]:
    """Map Prowler OCSF Detection-Finding records to normalized findings.

    Records missing a check id are skipped (logged), never guessed.
    """
    findings: list[NormalizedPostureFinding] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        metadata = record.get("metadata") or {}
        finding_info = record.get("finding_info") or {}
        cloud = record.get("cloud") or {}
        account = cloud.get("account") or {}
        resource = _first_resource(record)
        group = resource.get("group") or {}
        remediation = record.get("remediation") or {}
        unmapped = record.get("unmapped") or {}

        check_id = (metadata.get("event_code") or unmapped.get("check_id") or "").strip()
        if not check_id:
            logger.warning("prowler_parse skipped a record with no check id")
            continue

        findings.append(
            NormalizedPostureFinding(
                check_id=check_id[:128],
                title=(finding_info.get("title") or "")[:512],
                severity=severity_from_prowler(record.get("severity")),
                status=status_from_prowler(record.get("status_code")),
                account_id=str(account.get("uid") or "")[:32],
                region=(cloud.get("region") or resource.get("region") or "")[:32],
                service=(group.get("name") or "")[:64],
                resource_uid=(resource.get("uid") or "")[:512],
                resource_name=(resource.get("name") or "")[:255],
                resource_type=(resource.get("type") or "")[:128],
                finding_uid=(finding_info.get("uid") or "")[:255],
                description=finding_info.get("desc") or record.get("risk_details") or "",
                remediation=remediation.get("desc") or "",
                compliance=unmapped.get("compliance") or {},
            )
        )
    return findings


def ingest_prowler_scan(
    *,
    workspace_id: UUID,
    account_id: str,
    records: list[dict],
    connection_id: UUID | None = None,
    engine_version: str = "",
):
    """Persist one Prowler run as a scan + its actionable findings. Returns the scan."""
    from infrastructure.persistence.cloud_posture.models import CloudPostureFinding, CloudPostureScan

    findings = parse_prowler_ocsf(records)
    passed = sum(1 for f in findings if f.status is CheckStatus.PASS)
    failed = sum(1 for f in findings if f.status is CheckStatus.FAIL)
    now = timezone.now()

    scan = CloudPostureScan.objects.create(
        workspace_id=workspace_id,
        connection_id=connection_id,
        account_id=str(account_id or ""),
        engine_version=engine_version,
        status=CloudPostureScan.Status.COMPLETED,
        total_checks=len(findings),
        passed_count=passed,
        failed_count=failed,
        started_at=now,
        completed_at=now,
    )

    created = 0
    for finding in findings:
        if not finding.is_actionable:
            continue
        _, was_created = CloudPostureFinding.objects.get_or_create(
            scan=scan,
            check_id=finding.check_id,
            resource_uid=finding.resource_uid,
            defaults={
                "workspace_id": workspace_id,
                "title": finding.title,
                "severity": str(finding.severity),
                "status": str(finding.status),
                "account_id": finding.account_id,
                "region": finding.region,
                "service": finding.service,
                "resource_name": finding.resource_name,
                "resource_type": finding.resource_type,
                "finding_uid": finding.finding_uid,
                "description": finding.description,
                "remediation": finding.remediation,
                "compliance": dict(finding.compliance),
            },
        )
        created += int(was_created)

    logger.info(
        "prowler_ingest workspace_id=%s account=%s checks=%s failed=%s findings_created=%s",
        workspace_id,
        account_id,
        len(findings),
        failed,
        created,
    )
    return scan
