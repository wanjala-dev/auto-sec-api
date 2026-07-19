"""The normalized gallery row — the one shape every template kind presents.

A ``TemplateSummary`` is the kernel's lingua franca: each kind's source adapter
maps its own payload table onto this, so the unified gallery (``GET /templates/``)
and the frontend ``TemplateGallery`` speak ONE shape regardless of whether the
underlying template is a workflow graph, a budget's line items, or an HTML letter.

It carries identity + the cross-cutting spine (scope, category, version,
lifecycle), never the payload — the payload is fetched from the owning context's
detail endpoint when the user opens/applies a template.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TemplateSummary:
    id: str
    kind: str  # the kind id, e.g. "workflow_template" (see TemplateKindSpec)
    name: str
    scope: str  # "system" | "workspace"
    description: str = ""
    category: str = ""
    workspace_id: str | None = None  # None for system templates
    version: int = 1
    is_system: bool = False
    updated_at: str | None = None
    # Lightweight thumbnail source (task #13): {"layout": {...}} for design
    # templates, {"body_html": "..."} for prose ones, None when the kind's
    # spec exposes no preview fields.
    preview: dict | None = None
    # Target platform for social templates (task #28) — sourced from the
    # row's ``metadata.platform`` (linkedin|instagram|tiktok|facebook);
    # "" for kinds/rows without one.
    platform: str = ""

    def __post_init__(self) -> None:
        if self.scope not in ("system", "workspace"):
            raise ValueError(f"scope must be 'system' or 'workspace', got {self.scope!r}")
        if not self.id:
            raise ValueError("TemplateSummary requires an id")
        if not self.kind:
            raise ValueError("TemplateSummary requires a kind")
