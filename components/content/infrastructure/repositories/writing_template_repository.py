"""ORM-backed WritingTemplate store + reads (combined)."""

from __future__ import annotations

from typing import Any, Sequence
from uuid import UUID

from django.db.models import Q

from components.content.application.ports.writing_template_reader_port import (
    WritingTemplateReaderPort,
)
from components.content.application.ports.writing_template_store_port import (
    WritingTemplateStorePort,
)
from components.content.domain.entities.writing_template_entity import (
    WritingTemplateEntity,
)
from components.content.domain.enums import WritingTemplateKind
from components.content.domain.errors import WritingTemplateNotFoundError


def _to_entity(row) -> WritingTemplateEntity:
    return WritingTemplateEntity(
        id=row.id,
        name=row.name,
        description=row.description or "",
        kind=row.kind,
        body_html=row.body_html or "",
        is_seeded=row.is_seeded,
        workspace_id=row.workspace_id,
        metadata=dict(row.metadata or {}),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class WritingTemplateRepository(WritingTemplateStorePort, WritingTemplateReaderPort):
    # ── Store ─────────────────────────────────────────────────────────

    def create(
        self,
        *,
        name: str,
        description: str,
        kind: str,
        body_html: str,
        is_seeded: bool = False,
        workspace_id: UUID | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> WritingTemplateEntity:
        from infrastructure.persistence.content.models import WritingTemplate

        WritingTemplateKind.validate(kind)
        row = WritingTemplate.objects.create(
            name=name,
            description=description,
            kind=kind,
            body_html=body_html,
            is_seeded=is_seeded,
            workspace_id=workspace_id,
            metadata=metadata or {},
        )
        return _to_entity(row)

    def update(
        self,
        *,
        template_id: UUID,
        name: str,
        description: str,
        body_html: str,
    ) -> WritingTemplateEntity:
        from infrastructure.persistence.content.models import WritingTemplate

        try:
            row = WritingTemplate.objects.get(pk=template_id)
        except WritingTemplate.DoesNotExist as exc:
            raise WritingTemplateNotFoundError(str(template_id)) from exc
        row.name = name
        row.description = description
        row.body_html = body_html
        row.save(update_fields=["name", "description", "body_html", "updated_at"])
        return _to_entity(row)

    def delete(self, *, template_id: UUID) -> None:
        from infrastructure.persistence.content.models import WritingTemplate

        WritingTemplate.objects.filter(pk=template_id).delete()

    # ── Read ──────────────────────────────────────────────────────────

    def get(self, *, template_id: UUID) -> WritingTemplateEntity | None:
        from infrastructure.persistence.content.models import WritingTemplate

        row = WritingTemplate.objects.filter(pk=template_id, is_deleted=False).first()
        return _to_entity(row) if row else None

    def list_available(
        self,
        *,
        workspace_id: UUID,
        kind: str | None = None,
    ) -> Sequence[WritingTemplateEntity]:
        from infrastructure.persistence.content.models import WritingTemplate

        qs = WritingTemplate.objects.filter(
            Q(workspace__isnull=True) | Q(workspace_id=workspace_id)
        ).filter(is_deleted=False)  # trashed templates (recycle bin) stay hidden
        if kind:
            qs = qs.filter(kind=kind)
        return [_to_entity(row) for row in qs.order_by("-created_at")]

    def list_seeded(self, *, kind: str | None = None) -> Sequence[WritingTemplateEntity]:
        from infrastructure.persistence.content.models import WritingTemplate

        qs = WritingTemplate.objects.filter(is_seeded=True, is_deleted=False)
        if kind:
            qs = qs.filter(kind=kind)
        return [_to_entity(row) for row in qs.order_by("name")]
