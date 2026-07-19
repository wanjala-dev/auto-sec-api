"""Composition root for the Template Kernel — the kind registry.

Holds one ``TemplateSourcePort`` per kind so the unified gallery can fan out
across kinds. Mirrors the recycle-bin ``SoftDeleteProvider`` pattern: a single
place that wires every kind, lazily initialized.

Phase 1a registers the read-only sources via the generic configurable adapter
(spec-driven, no per-kind class). New kinds are added in ``TEMPLATE_KINDS`` —
config-only — and picked up here automatically.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from components.templates.application.ports.template_source_port import TemplateSourcePort
from components.templates.domain.entities.template_summary_entity import TemplateSummary
from components.templates.domain.errors import UnknownTemplateKind


class TemplateRegistry:
    def __init__(self) -> None:
        self._sources: Dict[str, TemplateSourcePort] = {}

    def register(self, source: TemplateSourcePort) -> None:
        self._sources[source.kind()] = source

    def kinds(self) -> List[str]:
        return sorted(self._sources.keys())

    def source_for(self, kind: str) -> TemplateSourcePort:
        source = self._sources.get(kind)
        if source is None:
            raise UnknownTemplateKind(kind)
        return source

    def list_templates(
        self, workspace_id: Optional[str], kind: Optional[str] = None
    ) -> List[TemplateSummary]:
        """List templates for one kind, or across all registered kinds."""
        if kind is not None:
            return self.source_for(kind).list_templates(workspace_id)
        out: List[TemplateSummary] = []
        for source in self._sources.values():
            out.extend(source.list_templates(workspace_id))
        return out


_registry: TemplateRegistry | None = None


def get_template_registry() -> TemplateRegistry:
    """Return the lazily-initialized, fully-wired TemplateRegistry singleton."""
    global _registry
    if _registry is not None:
        return _registry

    from components.templates.domain.template_kind import TEMPLATE_KINDS
    from components.templates.infrastructure.adapters.configurable_template_source_adapter import (
        ConfigurableTemplateSourceAdapter,
    )

    registry = TemplateRegistry()
    for spec in TEMPLATE_KINDS.values():
        registry.register(ConfigurableTemplateSourceAdapter(spec))

    _registry = registry
    return _registry
