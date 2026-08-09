"""Parse + normalize Prowler OCSF JSON — the pillar's PURE normalizer (audit R2).

Prowler (Apache-2.0) is the detection engine; this wraps its output. The parser
is pure (external JSON → domain entities) and engine-version-tolerant (defensive
field access); ``records_to_scan_result`` maps the actionable checks to the
shared ``NormalizedFinding`` shape under the given ``PostureProvider``'s
source/URN identity. PERSISTENCE lives on the spine: ``run_scan_and_ingest``
records the ``ScanRun`` and emits ``FindingObserved`` into the ONE Finding SSOT
— the legacy ``CloudPostureScan``/``CloudPostureFinding`` snapshot path (the
ADR 0004 C6 violation) is deleted.

OCSF field paths (Prowler v4/v5): ``metadata.event_code`` (check id),
``status_code``, ``severity``, ``finding_info.{uid,title,desc}``,
``resources[].{uid,name,type,region,group.name}``, ``cloud.account.uid``,
``cloud.region``, ``unmapped.compliance``, ``remediation.desc``.
"""

from __future__ import annotations

import logging

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
