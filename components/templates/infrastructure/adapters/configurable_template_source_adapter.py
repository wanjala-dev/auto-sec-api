"""One generic ``TemplateSourcePort`` that lists ANY kind from its spec.

Driven entirely by a ``TemplateKindSpec`` (which model, which fields). The model
is resolved at runtime via ``apps.get_model`` so the kernel never imports another
context's persistence module — keeping it decoupled and architecture-test clean.

Listing rule: a workspace sees its OWN templates (``workspace_id == ws``) PLUS the
system/global templates (``workspace_id IS NULL``). If the model carries
``is_deleted`` it is honored so trashed templates drop out of the gallery.
"""

from __future__ import annotations

import logging

from django.apps import apps
from django.db.models import Q

from components.templates.application.ports.template_source_port import TemplateSourcePort
from components.templates.domain.entities.template_summary_entity import TemplateSummary
from components.templates.domain.template_kind import TemplateKindSpec

logger = logging.getLogger(__name__)


class ConfigurableTemplateSourceAdapter(TemplateSourcePort):
    def __init__(self, spec: TemplateKindSpec) -> None:
        self._spec = spec

    def kind(self) -> str:
        return self._spec.id

    def list_templates(self, workspace_id: str | None) -> list[TemplateSummary]:
        spec = self._spec
        model = apps.get_model(spec.model_label)
        field_names = {f.name for f in model._meta.get_fields()}

        qs = model.objects.all()
        if "is_deleted" in field_names:
            qs = qs.filter(is_deleted=False)

        # Workspace's own templates + system (NULL-workspace) templates.
        scope_q = Q(**{f"{spec.workspace_field}__isnull": True})
        if workspace_id:
            scope_q |= Q(**{spec.workspace_field: workspace_id})
        qs = qs.filter(scope_q).order_by(spec.name_field)

        summaries: list[TemplateSummary] = []
        for row in qs:
            ws_val = getattr(row, spec.workspace_field, None)
            is_system = ws_val in (None, "")
            summaries.append(
                TemplateSummary(
                    id=str(row.pk),
                    kind=spec.id,
                    name=str(getattr(row, spec.name_field, "") or ""),
                    description=str(getattr(row, spec.description_field, "") or "") if spec.description_field else "",
                    category=self._category(row, spec),
                    scope="system" if is_system else "workspace",
                    workspace_id=None if is_system else str(ws_val),
                    version=self._version(row, spec),
                    is_system=is_system,
                    updated_at=self._updated_at(row),
                    preview=self._preview(row, spec),
                    platform=self._platform(row),
                )
            )
        return summaries

    @staticmethod
    def _platform(row) -> str:
        """Social templates carry their target platform in ``metadata``
        (task #28); other kinds/rows simply have none."""
        metadata = getattr(row, "metadata", None)
        if isinstance(metadata, dict):
            return str(metadata.get("platform") or "")
        return ""

    @staticmethod
    def _preview(row, spec: TemplateKindSpec):
        """Thumbnail source per the spec (task #13). A design template's
        block layout wins; otherwise a trimmed body_html; None when the
        kind exposes neither."""
        if spec.preview_layout_field:
            metadata = getattr(row, spec.preview_layout_field, None) or {}
            layout = metadata.get("layout") if isinstance(metadata, dict) else None
            if isinstance(layout, dict) and layout.get("blocks"):
                return {"layout": layout}
        if spec.preview_body_field:
            body = getattr(row, spec.preview_body_field, "") or ""
            if body:
                return {"body_html": body[:4000]}
        return None

    @staticmethod
    def _category(row, spec: TemplateKindSpec) -> str:
        if spec.category_field:
            return str(getattr(row, spec.category_field, "") or spec.category)
        return spec.category

    @staticmethod
    def _version(row, spec: TemplateKindSpec) -> int:
        if not spec.version_field:
            return 1
        raw = getattr(row, spec.version_field, 1)
        try:
            return int(raw)
        except (TypeError, ValueError):
            return 1

    @staticmethod
    def _updated_at(row) -> str | None:
        ts = getattr(row, "updated_at", None) or getattr(row, "modified", None)
        return str(ts) if ts else None
