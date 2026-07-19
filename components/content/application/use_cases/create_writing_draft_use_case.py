"""Use case: human composes a new writing draft (letter / update / summary / memo)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from components.content.application.ports.writing_draft_store_port import (
    WritingDraftStorePort,
)
from components.content.application.ports.writing_template_reader_port import (
    WritingTemplateReaderPort,
)
from components.content.domain.entities.writing_draft_entity import (
    WritingDraftEntity,
)
from components.content.domain.enums import WritingDraftKind
from components.shared_kernel.domain.errors import ValidationError


@dataclass
class CreateWritingDraftUseCase:
    writing_drafts: WritingDraftStorePort
    writing_templates: WritingTemplateReaderPort
    # Optional resolver — when set, ``{{placeholder}}`` tokens in the
    # template body are substituted with workspace-derived values
    # (donations_count, recipient_count, etc.) before the draft is
    # created. Falls back to passing the template body through unchanged
    # if resolution fails — the editor highlights unresolved tokens so
    # the user can fill them in.
    placeholder_resolver: Any = field(default=None)

    def execute(
        self,
        *,
        workspace_id: UUID,
        author_id: int,
        title: str,
        kind: str,
        body_html: str = "",
        template_id: UUID | None = None,
        related_entity_type: str = "",
        related_entity_id: UUID | None = None,
        metadata: dict[str, Any] | None = None,
        ai_drafted: bool = False,
    ) -> WritingDraftEntity:
        WritingDraftKind.validate(kind)

        # Entity-scoped kinds require their related-entity link; the
        # domain entity's __post_init__ enforces this, but raising the
        # error here gives the caller a clearer message + maps to the
        # 400 the controller surfaces.
        entity_scoped = {
            WritingDraftKind.RECIPIENT_UPDATE: "recipient",
            WritingDraftKind.PROJECT_UPDATE: "project",
            WritingDraftKind.EVENT_UPDATE: "event",
            WritingDraftKind.CAMPAIGN_UPDATE: "campaign",
        }
        expected_type = entity_scoped.get(kind)
        if expected_type is not None:
            if not related_entity_id:
                raise ValidationError(f"kind={kind!r} requires related_entity_id.")
            if not related_entity_type:
                # Allow the controller to omit the type when it can be
                # derived from the kind — saves the FE one field.
                related_entity_type = expected_type
            elif related_entity_type != expected_type:
                raise ValidationError(f"kind={kind!r} requires related_entity_type={expected_type!r}.")
        elif related_entity_type or related_entity_id:
            raise ValidationError(f"kind={kind!r} must not carry related_entity_* fields.")

        # Template seeding: if no body provided but a template is named,
        # copy the template body into the new draft. The author can edit
        # immediately; the template_id is recorded for analytics.
        if not body_html and template_id is not None:
            template = self.writing_templates.get(template_id=template_id)
            if template is not None and template.kind == kind:
                body_html = template.body_html
                if self.placeholder_resolver is not None and body_html:
                    body_html = self.placeholder_resolver.resolve(
                        body_html=body_html,
                        workspace_id=workspace_id,
                    )
                # DESIGN templates (task #19): a block-tree layout in the
                # template's metadata is copied onto the draft — with
                # workspace placeholders resolved — so summaries/blogs/etc.
                # composed from a design come up as the designed document,
                # exactly the way newsletter design templates apply. The
                # body_html copy above stays as the plain-render fallback.
                layout = (getattr(template, "metadata", None) or {}).get("layout")
                if isinstance(layout, dict) and layout.get("blocks"):
                    from components.content.application.services.layout_placeholder_service import (
                        resolve_layout_placeholders,
                    )
                    from components.content.application.use_cases.generate_newsletter_use_case import (
                        _workspace_donate_url,
                    )

                    try:
                        donate_url = _workspace_donate_url(workspace_id)
                    except Exception:
                        donate_url = ""
                    metadata = dict(metadata or {})
                    metadata["layout"] = resolve_layout_placeholders(
                        layout,
                        self.placeholder_resolver,
                        workspace_id,
                        donate_url=donate_url,
                    )

        return self.writing_drafts.create(
            workspace_id=workspace_id,
            author_id=author_id,
            title=title,
            body_html=body_html,
            kind=kind,
            template_id=template_id,
            ai_drafted=ai_drafted,
            related_entity_type=related_entity_type,
            related_entity_id=related_entity_id,
            metadata=metadata or {},
        )
