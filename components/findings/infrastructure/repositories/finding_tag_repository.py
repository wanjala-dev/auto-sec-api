"""Django adapter implementing FindingTagStorePort (ADR 0015 D10)."""

from __future__ import annotations

import uuid as uuid_module
from collections.abc import Sequence
from uuid import UUID

from components.findings.application.ports.finding_tag_store_port import FindingTagStorePort
from components.shared_kernel.domain.tagging import TagRef


class FindingTagRepository(FindingTagStorePort):
    def tag_ids_for_finding(self, workspace_id: UUID, finding_id: UUID) -> set[UUID]:
        from infrastructure.persistence.findings.models import FindingTag

        return set(
            FindingTag.objects.filter(workspace_id=workspace_id, finding_id=finding_id).values_list("tag_id", flat=True)
        )

    def add_tags(
        self,
        workspace_id: UUID,
        finding_id: UUID,
        tag_ids: Sequence[UUID],
        *,
        actor_id: str | None,
        source: str = "user",
    ) -> None:
        from infrastructure.persistence.findings.models import FindingTag

        if not tag_ids:
            return
        applied_by = UUID(actor_id) if actor_id else None
        # ignore_conflicts=True → idempotent re-adds (uniq_finding_tag wins, D6).
        FindingTag.objects.bulk_create(
            [
                FindingTag(
                    id=uuid_module.uuid4(),
                    workspace_id=workspace_id,
                    finding_id=finding_id,
                    tag_id=tag_id,
                    applied_by=applied_by,
                    source=source,
                )
                for tag_id in tag_ids
            ],
            ignore_conflicts=True,
        )

    def remove_tags(self, workspace_id: UUID, finding_id: UUID, tag_ids: Sequence[UUID]) -> None:
        from infrastructure.persistence.findings.models import FindingTag

        if not tag_ids:
            return
        FindingTag.objects.filter(workspace_id=workspace_id, finding_id=finding_id, tag_id__in=list(tag_ids)).delete()

    def refs_for_finding(self, workspace_id: UUID, finding_id: UUID) -> tuple[TagRef, ...]:
        from infrastructure.persistence.findings.models import FindingTag

        links = (
            FindingTag.objects.filter(workspace_id=workspace_id, finding_id=finding_id, tag__is_deleted=False)
            .select_related("tag")
            .order_by("tag__slug")
        )
        return tuple(
            TagRef(id=link.tag.id, slug=link.tag.slug, name=link.tag.name, color=link.tag.color) for link in links
        )
