"""Django adapter implementing FindingStorePort."""

from __future__ import annotations

from uuid import UUID

from components.findings.application.ports.finding_store_port import FindingStorePort
from components.findings.domain.entities.finding_entity import FindingEntity
from components.findings.mappers.db.finding_mapper import to_finding_defaults, to_finding_entity


class DjangoFindingRepository(FindingStorePort):
    def find_by_identity(self, workspace_id: UUID, source: str, fingerprint: str) -> FindingEntity | None:
        from infrastructure.persistence.findings.models import Finding

        obj = (
            Finding.objects.filter(workspace_id=workspace_id, source=source, fingerprint=fingerprint)
            .select_related("workspace")
            .first()
        )
        return to_finding_entity(obj) if obj else None

    def upsert(self, finding: FindingEntity) -> None:
        from infrastructure.persistence.findings.models import Finding

        Finding.objects.update_or_create(
            workspace_id=finding.workspace_id,
            source=finding.source,
            fingerprint=finding.fingerprint,
            defaults=to_finding_defaults(finding),
        )
