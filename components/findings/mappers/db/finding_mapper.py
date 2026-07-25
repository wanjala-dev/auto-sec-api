"""Mechanical ORM ↔ domain translation for Finding. No business logic."""

from __future__ import annotations

from components.findings.domain.entities.finding_entity import FindingEntity
from components.shared_kernel.domain.security import FindingStatus, Severity


def to_finding_entity(model) -> FindingEntity:
    return FindingEntity(
        id=model.id,
        workspace_id=model.workspace_id,
        source=model.source,
        fingerprint=model.fingerprint,
        asset_urn=model.asset_urn,
        severity=Severity.from_name(model.severity),
        status=FindingStatus(model.status),
        title=model.title,
        first_seen_at=model.first_seen_at,
        last_seen_at=model.last_seen_at,
        description=model.description,
        remediation=model.remediation,
        compliance=model.compliance or {},
        attributes=model.attributes or {},
        resolved_at=model.resolved_at,
    )


def to_finding_defaults(finding: FindingEntity) -> dict:
    """Field map for ``update_or_create(defaults=...)`` — everything except the
    identity lookup keys (workspace, source, fingerprint). ``id`` + ``first_seen_at``
    are included so a create uses the entity's values and an update is a no-op on them
    (the entity carries the existing values on the update path).
    """
    return {
        "id": finding.id,
        "asset_urn": finding.asset_urn,
        "severity": finding.severity.value,
        "status": finding.status.value,
        "title": finding.title,
        "description": finding.description,
        "remediation": finding.remediation,
        "compliance": finding.compliance,
        "attributes": finding.attributes,
        "first_seen_at": finding.first_seen_at,
        "last_seen_at": finding.last_seen_at,
        "resolved_at": finding.resolved_at,
    }
