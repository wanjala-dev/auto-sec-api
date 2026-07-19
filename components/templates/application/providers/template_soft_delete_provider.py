"""Provider exposing the template kinds' recycle-bin soft-delete adapters.

The recycle-bin composition root imports THIS (an application provider), not the
infrastructure adapter directly — keeping the cross-context boundary clean. Each
adapter is the generic ``ConfigurableTemplateSoftDeleteAdapter`` parametrized per
kind.

Phase 1a: only kinds whose table already carries ``is_deleted`` register here.
BudgetTemplate has it (StandardMetadata). Writing/Workflow templates join once
the Phase-1b ``TemplateBase`` migration adds ``is_deleted`` — at which point they
are appended to this list (config-only). See the consolidation doc.
"""

from __future__ import annotations

from components.recycle_bin.application.ports.soft_delete_port import SoftDeletePort

# Kinds whose table carries ``is_deleted`` and can be trashed to the recycle bin.
_DELETABLE_KINDS = [
    {"model_label": "workflows.WorkflowTemplate", "entity_type": "workflow_template", "name_field": "label"},
    {
        "model_label": "security_templates.SecurityReportTemplate",
        "entity_type": "security_report_template",
        "name_field": "name",
    },
]


def get_template_soft_delete_adapters() -> list[SoftDeletePort]:
    from components.templates.infrastructure.adapters.configurable_template_soft_delete_adapter import (
        ConfigurableTemplateSoftDeleteAdapter,
    )

    return [ConfigurableTemplateSoftDeleteAdapter(**cfg) for cfg in _DELETABLE_KINDS]
