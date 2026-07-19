"""Output DTO for the unified gallery — the API-boundary shape of a template.

Mirrors the ``TemplateSummary`` domain entity but is the explicit
primary-adapter resource the controller serializes, keeping the domain entity
free of any API-shape coupling.
"""

from __future__ import annotations

from dataclasses import dataclass

from components.templates.domain.entities.template_summary_entity import TemplateSummary


@dataclass(frozen=True)
class TemplateSummaryResource:
    id: str
    kind: str
    name: str
    scope: str
    description: str
    category: str
    workspace_id: str | None
    version: int
    is_system: bool
    updated_at: str | None
    # Thumbnail source (task #13): {"layout": {...}} | {"body_html": "..."} | None.
    preview: dict | None
    # Social target platform (task #28): linkedin|instagram|tiktok|facebook|"".
    platform: str = ""

    @classmethod
    def from_summary(cls, summary: TemplateSummary) -> TemplateSummaryResource:
        return cls(
            id=summary.id,
            kind=summary.kind,
            name=summary.name,
            scope=summary.scope,
            description=summary.description,
            category=summary.category,
            workspace_id=summary.workspace_id,
            version=summary.version,
            is_system=summary.is_system,
            updated_at=summary.updated_at,
            preview=summary.preview,
            platform=summary.platform,
        )
