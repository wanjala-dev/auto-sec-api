"""Output DTO for the findings read API — maps a FindingEntity to a JSON-safe dict."""

from __future__ import annotations

from components.findings.application.queries.list_findings_query import FindingPage
from components.findings.domain.entities.finding_entity import FindingEntity


class FindingResource:
    @staticmethod
    def from_entity(e: FindingEntity) -> dict:
        return {
            "id": str(e.id),
            "source": e.source,
            "fingerprint": e.fingerprint,
            "asset_urn": e.asset_urn,
            "severity": e.severity.value,
            "status": e.status.value,
            "is_open": e.is_open,
            "title": e.title,
            "description": e.description,
            "remediation": e.remediation,
            "compliance": e.compliance,
            "attributes": e.attributes,
            "first_seen_at": e.first_seen_at.isoformat() if e.first_seen_at else None,
            "last_seen_at": e.last_seen_at.isoformat() if e.last_seen_at else None,
            "resolved_at": e.resolved_at.isoformat() if e.resolved_at else None,
        }

    @staticmethod
    def page(page: FindingPage) -> dict:
        return {
            "items": [FindingResource.from_entity(e) for e in page.items],
            "total": page.total,
            "limit": page.limit,
            "offset": page.offset,
        }
