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

    def find_by_id(self, workspace_id: UUID, finding_id: UUID) -> FindingEntity | None:
        from infrastructure.persistence.findings.models import Finding

        obj = Finding.objects.filter(workspace_id=workspace_id, id=finding_id).select_related("workspace").first()
        return to_finding_entity(obj) if obj else None

    def _filtered(self, workspace_id, *, severity, status, source, asset_urn):
        # One place builds the WHERE so list + count never drift. select_related is
        # applied on the list path; count() ignores it. Index-backed on
        # (workspace, severity|status, -last_seen_at).
        from infrastructure.persistence.findings.models import Finding

        qs = Finding.objects.filter(workspace_id=workspace_id)
        if severity:
            qs = qs.filter(severity=severity)
        if status:
            qs = qs.filter(status=status)
        if source:
            qs = qs.filter(source=source)
        if asset_urn:
            qs = qs.filter(asset_urn=asset_urn)
        return qs

    def list_findings(
        self,
        workspace_id: UUID,
        *,
        severity: str | None = None,
        status: str | None = None,
        source: str | None = None,
        asset_urn: str | None = None,
        limit: int = 25,
        offset: int = 0,
    ) -> list[FindingEntity]:
        qs = (
            self._filtered(workspace_id, severity=severity, status=status, source=source, asset_urn=asset_urn)
            .select_related("workspace")
            .order_by("-last_seen_at", "-first_seen_at")
        )
        rows = qs[offset : offset + limit]
        return [to_finding_entity(obj) for obj in rows]

    def count_findings(
        self,
        workspace_id: UUID,
        *,
        severity: str | None = None,
        status: str | None = None,
        source: str | None = None,
        asset_urn: str | None = None,
    ) -> int:
        return self._filtered(
            workspace_id, severity=severity, status=status, source=source, asset_urn=asset_urn
        ).count()

    def upsert(self, finding: FindingEntity) -> None:
        from infrastructure.persistence.findings.models import Finding

        Finding.objects.update_or_create(
            workspace_id=finding.workspace_id,
            source=finding.source,
            fingerprint=finding.fingerprint,
            defaults=to_finding_defaults(finding),
        )
