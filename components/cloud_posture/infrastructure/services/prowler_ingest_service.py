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
from collections import Counter
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from components.cloud_posture.domain.entities.posture_finding_entity import NormalizedPostureFinding
from components.cloud_posture.domain.posture_provider import (
    PostureProvider,
    resolve_posture_provider,
)
from components.cloud_posture.domain.value_objects.enums import (
    CheckStatus,
    severity_from_prowler,
    status_from_prowler,
)
from components.shared_kernel.application.ports.scanner_port import ScanResult
from components.shared_kernel.domain.events import FindingObserved, ScanCompleted
from components.shared_kernel.domain.security import AssetUrn, NormalizedFinding, Severity

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
    event_publisher=None,
    provider: PostureProvider | None = None,
):
    """Convenience: ingest raw Prowler OCSF records (parse → normalize → ingest).

    A thin wrapper over ``records_to_scan_result`` + ``ingest_scan_result`` for callers
    that hold raw records (tests). The Celery scan task goes through the ``ProwlerScanner``
    ScannerPort adapter (ADR 0004 Phase 4) instead. ``provider`` defaults to AWS —
    every pre-ADR-0021 caller is an AWS caller.
    """
    provider = provider or resolve_posture_provider(None)
    result = records_to_scan_result(records, engine_version=engine_version or "prowler", provider=provider)
    return ingest_scan_result(
        workspace_id=workspace_id,
        account_id=account_id,
        result=result,
        connection_id=connection_id,
        event_publisher=event_publisher,
        provider=provider,
    )


def ingest_scan_result(
    *,
    workspace_id: UUID,
    account_id: str,
    result: ScanResult,
    connection_id: UUID | None = None,
    event_publisher=None,
    provider: PostureProvider | None = None,
):
    """Persist a scan result: the CSPM snapshot + a dual-write into the findings SSOT.

    The engine-agnostic ingest — given a ``ScanResult`` from any ScannerPort adapter
    (Prowler today), record the ``CloudPostureScan`` snapshot + its ``CloudPostureFinding``
    rows (CSPM specifics read from each finding's ``attributes``), and emit one
    ``FindingObserved`` per finding for the SSOT (ADR 0004). cloud_posture stays
    decoupled: it publishes a shared-kernel event and never imports the findings context.
    ``event_publisher`` is injectable for tests.
    """
    from infrastructure.persistence.cloud_posture.models import CloudPostureFinding, CloudPostureScan

    provider = provider or resolve_posture_provider(None)
    now = timezone.now()
    scan = CloudPostureScan.objects.create(
        workspace_id=workspace_id,
        connection_id=connection_id,
        account_id=str(account_id or ""),
        engine_version=result.engine_version,
        status=CloudPostureScan.Status.COMPLETED,
        total_checks=result.total_checks,
        passed_count=result.passed_count,
        failed_count=result.failed_count,
        started_at=now,
        completed_at=now,
    )

    created = 0
    observed_events = []
    for finding in result.findings:
        attrs = finding.attributes or {}
        _, was_created = CloudPostureFinding.objects.get_or_create(
            scan=scan,
            check_id=attrs.get("check_id", ""),
            resource_uid=attrs.get("resource_uid", ""),
            defaults={
                "workspace_id": workspace_id,
                "title": finding.title,
                "severity": finding.severity.value,
                "status": attrs.get("check_status", ""),
                "account_id": attrs.get("account_id", ""),
                "region": attrs.get("region", ""),
                "service": attrs.get("service", ""),
                "resource_name": attrs.get("resource_name", ""),
                "resource_type": attrs.get("resource_type", ""),
                "finding_uid": attrs.get("finding_uid", ""),
                "description": finding.description,
                "remediation": finding.remediation,
                "compliance": dict(finding.compliance),
            },
        )
        created += int(was_created)
        observed_events.append(_finding_observed_from_normalized(workspace_id, finding))

    # One ScanCompleted per ingest — the anti-flood digest signal (ADR 0016 D5):
    # the notifications context turns it into ONE external message per scan.
    severity_counts = Counter(f.severity.value for f in result.findings)
    completed_event = ScanCompleted(
        workspace_id=workspace_id,
        source=provider.source,
        engine=result.engine or "prowler",
        scan_id=str(scan.id),
        target_ref=str(account_id or ""),
        account_id=str(account_id or ""),
        total_checks=result.total_checks,
        findings_observed=len(observed_events),
        critical=severity_counts.get("critical", 0),
        high=severity_counts.get("high", 0),
        medium=severity_counts.get("medium", 0),
        low=severity_counts.get("low", 0),
    )

    _publish_events([*observed_events, completed_event], event_publisher)

    logger.info(
        "cloud_posture_ingest workspace_id=%s account=%s checks=%s failed=%s findings_created=%s observed=%s",
        workspace_id,
        account_id,
        result.total_checks,
        result.failed_count,
        created,
        len(observed_events),
    )
    return scan


def _to_normalized(finding: NormalizedPostureFinding, provider: PostureProvider | None = None) -> NormalizedFinding:
    """Map a rich CSPM finding to the shared normalized shape (CSPM specifics → attributes).

    ``fingerprint`` is stable across scans for the same misconfiguration on the same
    resource; ``asset_urn`` is the resource ref canonicalised under the PROVIDER's
    namespace (an AWS ARN passes through verbatim; an opaque Vercel id becomes
    ``urn:vercel:<ref>``), or a per-account URN for account-level checks so the
    required identity is never empty. The source, URN namespace, and fingerprint
    identity key all come from the ``PostureProvider`` — never a string literal
    (ADR 0021 D1; a fitness test enforces this structurally).
    """
    provider = provider or resolve_posture_provider(None)
    resource_ref = finding.resource_uid or f"account/{finding.account_id or 'unknown'}"
    attributes = {
        "check_id": finding.check_id,
        "account_id": finding.account_id,
        "region": finding.region,
        "service": finding.service,
        "resource_type": finding.resource_type,
        "resource_name": finding.resource_name,
        "resource_uid": finding.resource_uid,
        "finding_uid": finding.finding_uid,
        "check_status": str(finding.status),
    }
    attributes.update(provider.extra_attributes(finding))
    return NormalizedFinding(
        source=provider.source,
        fingerprint=f"{finding.check_id}|{provider.identity_key(finding)}|{finding.resource_uid}",
        asset_urn=AssetUrn.canonical(provider.token, resource_ref).value,
        severity=Severity.from_name(str(finding.severity)),
        title=finding.title or finding.check_id,
        description=finding.description,
        remediation=finding.remediation,
        compliance=dict(finding.compliance),
        attributes=attributes,
    )


def records_to_scan_result(
    records: list[dict], *, engine_version: str = "", provider: PostureProvider | None = None
) -> ScanResult:
    """Parse Prowler OCSF records → a ``ScanResult`` (pure: no engine, no DB).

    Counts come from ALL parsed checks (including passes); ``findings`` are the
    actionable ones mapped to the shared ``NormalizedFinding`` shape under the
    given provider's source/URN identity (default AWS — ADR 0021 D1).
    """
    provider = provider or resolve_posture_provider(None)
    parsed = parse_prowler_ocsf(records)
    passed = sum(1 for f in parsed if f.status is CheckStatus.PASS)
    failed = sum(1 for f in parsed if f.status is CheckStatus.FAIL)
    findings = tuple(_to_normalized(f, provider) for f in parsed if f.is_actionable)
    return ScanResult(
        findings=findings,
        engine="prowler",
        engine_version=engine_version or "prowler",
        total_checks=len(parsed),
        passed_count=passed,
        failed_count=failed,
    )


def _finding_observed_from_normalized(workspace_id: UUID, finding: NormalizedFinding) -> FindingObserved:
    """Map a ``NormalizedFinding`` to a ``FindingObserved`` event for the SSOT dual-write."""
    return FindingObserved(
        workspace_id=workspace_id,
        source=finding.source,
        fingerprint=finding.fingerprint,
        asset_urn=finding.asset_urn,
        severity=finding.severity.value,
        title=finding.title,
        description=finding.description,
        remediation=finding.remediation,
        compliance=dict(finding.compliance),
        attributes=dict(finding.attributes),
    )


def _publish_events(events: list, event_publisher) -> None:
    """Publish the scan's events (FindingObserved* + ScanCompleted) after its rows commit.

    ``on_commit`` guards against publishing into an outer transaction that later rolls
    back (which would leave orphan findings). No-op when there is nothing to emit.
    """
    if not events:
        return

    def _emit(publisher=event_publisher) -> None:
        if publisher is None:
            from components.shared_kernel.infrastructure.adapters.celery_event_publisher import (
                CeleryEventPublisher,
            )

            publisher = CeleryEventPublisher()
        for event in events:
            publisher.publish(event)

    transaction.on_commit(_emit)
