"""Django adapter implementing FindingStorePort."""

from __future__ import annotations

from collections.abc import Iterator
from uuid import UUID

from components.findings.application.ports.finding_store_port import FindingStorePort
from components.findings.application.queries.list_findings_query import (
    ORDER_CONTEXTUAL_RISK,
    FindingRiskView,
    RankedFinding,
)
from components.findings.domain.entities.finding_entity import FindingEntity
from components.findings.mappers.db.finding_mapper import (
    to_finding_create_defaults,
    to_finding_defaults,
    to_finding_entity,
)


def _to_risk_view(risk_model) -> FindingRiskView | None:
    """Read-side FindingRisk row → view. None → the finding is not yet scored."""
    if risk_model is None:
        return None
    return FindingRiskView(
        score=risk_model.score,
        band=risk_model.band,
        epss=risk_model.epss,
        epss_percentile=risk_model.epss_percentile,
        in_kev=risk_model.in_kev,
        exposure=risk_model.exposure,
        exposure_unknown=risk_model.exposure_unknown,
        factors=risk_model.factors or [],
    )


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

    def get_ranked_finding(self, workspace_id: UUID, finding_id: UUID) -> RankedFinding | None:
        from infrastructure.persistence.findings.models import Finding

        # Same eager-load shape as list_ranked_findings: risk via the OneToOne JOIN,
        # tag chips via the prefetch — one row, constant queries.
        obj = (
            self._with_tag_prefetch(
                Finding.objects.filter(workspace_id=workspace_id, id=finding_id).select_related("workspace", "risk")
            )
        ).first()
        if obj is None:
            return None
        return RankedFinding(finding=to_finding_entity(obj), risk=_to_risk_view(getattr(obj, "risk", None)))

    def _filtered(self, workspace_id, *, severity, status, source, asset_urn, tag_groups=(), exclude_tag_ids=()):
        # One place builds the WHERE so list + count never drift. select_related is
        # applied on the list path; count() ignores it. Index-backed on
        # (workspace, severity|status, -last_seen_at).
        from django.db.models import Exists, OuterRef

        from infrastructure.persistence.findings.models import Finding, FindingTag

        qs = Finding.objects.filter(workspace_id=workspace_id)
        if severity:
            qs = qs.filter(severity=severity)
        if status:
            qs = qs.filter(status=status)
        if source:
            qs = qs.filter(source=source)
        if asset_urn:
            qs = qs.filter(asset_urn=asset_urn)
        # Tag filter (ADR 0015 D7): ``Exists()`` subqueries — NOT chained M2M joins —
        # so rows never multiply and no DISTINCT is needed; each subquery is one probe
        # of findingtag_ws_tag_idx / the uniq_finding_tag index.
        for group in tag_groups:
            if not group:
                # An OR-group that resolved to zero live tags matches nothing (D7).
                return qs.none()
            qs = qs.filter(Exists(FindingTag.objects.filter(finding=OuterRef("pk"), tag_id__in=group)))
        for tag_id in exclude_tag_ids:
            qs = qs.filter(~Exists(FindingTag.objects.filter(finding=OuterRef("pk"), tag_id=tag_id)))
        return qs

    @staticmethod
    def _with_tag_prefetch(qs):
        """Chip read (ADR 0015 D7): ONE extra query per page regardless of row count —
        the live tag links with their tags, projected by the mapper into
        ``FindingEntity.tags``."""
        from django.db.models import Prefetch

        from infrastructure.persistence.findings.models import FindingTag

        return qs.prefetch_related(
            Prefetch(
                "tag_links",
                queryset=FindingTag.objects.filter(tag__is_deleted=False).select_related("tag").order_by("tag__slug"),
                to_attr="prefetched_tag_links",
            )
        )

    def list_findings(
        self,
        workspace_id: UUID,
        *,
        severity: str | None = None,
        status: str | None = None,
        source: str | None = None,
        asset_urn: str | None = None,
        tag_groups: tuple[tuple[UUID, ...], ...] = (),
        exclude_tag_ids: tuple[UUID, ...] = (),
        limit: int = 25,
        offset: int = 0,
    ) -> list[FindingEntity]:
        qs = (
            self._filtered(
                workspace_id,
                severity=severity,
                status=status,
                source=source,
                asset_urn=asset_urn,
                tag_groups=tag_groups,
                exclude_tag_ids=exclude_tag_ids,
            )
            .select_related("workspace")
            .order_by("-last_seen_at", "-first_seen_at")
        )
        rows = qs[offset : offset + limit]
        return [to_finding_entity(obj) for obj in rows]

    def list_ranked_findings(
        self,
        workspace_id: UUID,
        *,
        severity: str | None = None,
        status: str | None = None,
        source: str | None = None,
        asset_urn: str | None = None,
        tag_groups: tuple[tuple[UUID, ...], ...] = (),
        exclude_tag_ids: tuple[UUID, ...] = (),
        order_by: str = ORDER_CONTEXTUAL_RISK,
        limit: int = 25,
        offset: int = 0,
    ) -> list[RankedFinding]:
        from django.db.models import F

        # select_related("risk") pulls the OneToOne materialized score in the same query
        # (one JOIN, no N+1); the ranked read is index-backed on (workspace, -score).
        # _with_tag_prefetch adds the chip read: one extra query per page (ADR 0015 D7).
        qs = self._with_tag_prefetch(
            self._filtered(
                workspace_id,
                severity=severity,
                status=status,
                source=source,
                asset_urn=asset_urn,
                tag_groups=tag_groups,
                exclude_tag_ids=exclude_tag_ids,
            ).select_related("workspace", "risk")
        )

        if order_by == ORDER_CONTEXTUAL_RISK:
            # Highest score first; findings not yet scored sort last, then by recency.
            qs = qs.order_by(F("risk__score").desc(nulls_last=True), "-last_seen_at", "-first_seen_at")
        else:
            qs = qs.order_by("-last_seen_at", "-first_seen_at")

        rows = qs[offset : offset + limit]
        return [
            RankedFinding(
                finding=to_finding_entity(obj),
                risk=_to_risk_view(getattr(obj, "risk", None)),
            )
            for obj in rows
        ]

    def iter_scorable_findings(self, workspace_id: UUID, *, finding_id: UUID | None = None) -> Iterator[FindingEntity]:
        from infrastructure.persistence.findings.models import Finding

        qs = Finding.objects.filter(workspace_id=workspace_id).select_related("workspace")
        if finding_id is not None:
            qs = qs.filter(id=finding_id)
        for obj in qs.iterator(chunk_size=500):
            yield to_finding_entity(obj)

    def list_workspace_ids_with_findings(self) -> list[UUID]:
        from infrastructure.persistence.findings.models import Finding

        # Scope the daily feed-refresh fan-out to workspaces with NON-terminal findings (S3):
        # a resolved/suppressed-only workspace has nothing whose rank a feed move could change,
        # so rescoring it every day is wasted work.
        return list(
            Finding.objects.exclude(status__in=["resolved", "suppressed"])
            .values_list("workspace_id", flat=True)
            .distinct()
        )

    def count_findings(
        self,
        workspace_id: UUID,
        *,
        severity: str | None = None,
        status: str | None = None,
        source: str | None = None,
        asset_urn: str | None = None,
        tag_groups: tuple[tuple[UUID, ...], ...] = (),
        exclude_tag_ids: tuple[UUID, ...] = (),
    ) -> int:
        return self._filtered(
            workspace_id,
            severity=severity,
            status=status,
            source=source,
            asset_urn=asset_urn,
            tag_groups=tag_groups,
            exclude_tag_ids=exclude_tag_ids,
        ).count()

    def open_finding_asset_urns(self, workspace_id: UUID, *, severities: tuple[str, ...]) -> set[str]:
        from infrastructure.persistence.findings.models import Finding

        return set(
            Finding.objects.filter(workspace_id=workspace_id, status="open", severity__in=list(severities))
            .exclude(asset_urn="")
            .values_list("asset_urn", flat=True)
            .distinct()
        )

    def open_finding_compliance(self, workspace_id: UUID) -> list[dict]:
        from infrastructure.persistence.findings.models import Finding

        return list(
            Finding.objects.filter(workspace_id=workspace_id, status="open")
            .exclude(compliance={})
            .values_list("compliance", flat=True)
        )

    def upsert(self, finding: FindingEntity) -> None:
        from infrastructure.persistence.findings.models import Finding

        Finding.objects.update_or_create(
            workspace_id=finding.workspace_id,
            source=finding.source,
            fingerprint=finding.fingerprint,
            defaults=to_finding_defaults(finding),
            create_defaults=to_finding_create_defaults(finding),
        )

    def has_real_findings(self, workspace_id: UUID, *, sample_prefix: str) -> bool:
        from infrastructure.persistence.findings.models import Finding

        return Finding.objects.filter(workspace_id=workspace_id).exclude(source__startswith=sample_prefix).exists()

    def delete_sample_findings(self, workspace_id: UUID, *, sample_prefix: str) -> int:
        from infrastructure.persistence.findings.models import Finding

        deleted, _ = Finding.objects.filter(workspace_id=workspace_id, source__startswith=sample_prefix).delete()
        return deleted
