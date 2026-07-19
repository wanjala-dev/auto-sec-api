"""The catalogue of known template kinds + how to read each one generically.

A ``TemplateKindSpec`` is pure config: it tells the kernel's generic adapters
which ORM model backs a kind and which fields carry the name/description/version,
so the kernel can list (and later soft-delete) any kind WITHOUT importing the
owning context's code — the model is resolved at runtime via ``apps.get_model``.

The universal scoping rule across every kind: **a template whose ``workspace`` is
NULL is a system (global) template; otherwise it is workspace-owned.**

Field names vary per kind (e.g. the display name is ``label`` on WorkflowTemplate
but ``name`` on the report templates); the spec captures that variance as data.

Auto-Sec kinds (the nonprofit kinds from the source platform are dropped): the
automation ``WorkflowTemplate`` (already in the fork) and the security report
templates (pentest / RCA / incident / corrective-action / threat-brief) backed by
``security_templates.SecurityReportTemplate``. Adding a kind is config-only.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TemplateKindSpec:
    id: str  # canonical kind id, e.g. "workflow_template"
    label: str  # human label for the gallery section
    model_label: str  # "app_label.ModelName" — resolved via apps.get_model
    name_field: str = "name"
    description_field: str | None = "description"
    version_field: str | None = None  # None → version defaults to 1
    category_field: str | None = None  # None → use ``category`` default below
    category: str = ""  # static category when the model has no category column
    workspace_field: str = "workspace_id"
    # Optional card-thumbnail sources: ``preview_layout_field`` names a JSON
    # column whose ``["layout"]`` holds a block tree; ``preview_body_field``
    # names an HTML body used when no layout exists.
    preview_layout_field: str | None = None
    preview_body_field: str | None = None


# Adding a kind here is config-only (the generic adapter reads it via the spec).
TEMPLATE_KINDS: dict[str, TemplateKindSpec] = {
    "workflow_template": TemplateKindSpec(
        id="workflow_template",
        label="Workflow templates",
        model_label="workflows.WorkflowTemplate",
        name_field="label",
        version_field="version",
        category_field="category",
    ),
    "security_report_template": TemplateKindSpec(
        id="security_report_template",
        label="Security report templates",
        model_label="security_templates.SecurityReportTemplate",
        name_field="name",
        description_field="description",
        version_field="version",
        category_field="category",
        preview_body_field="body_html",
    ),
}


def get_kind_spec(kind: str) -> TemplateKindSpec:
    from components.templates.domain.errors import UnknownTemplateKind

    spec = TEMPLATE_KINDS.get(kind)
    if spec is None:
        raise UnknownTemplateKind(kind)
    return spec
