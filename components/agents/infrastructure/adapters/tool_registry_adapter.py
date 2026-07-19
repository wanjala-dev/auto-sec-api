"""Adapter wrapping the legacy detector registry behind ToolRegistryPort.

Translates between the ``apps.ai.actions.detectors.registry`` module-level
functions and the clean port contract.
"""
from __future__ import annotations

from typing import Any

from components.agents.application.ports.tool_registry_port import (
    ToolDescriptor,
    ToolRegistryPort,
)


class DetectorRegistryAdapter(ToolRegistryPort):
    """Wraps ``apps.ai.actions.detectors.registry`` as a ToolRegistryPort."""

    def _registry(self):
        from components.agents.infrastructure.adapters.actions.detectors import registry
        return registry

    def list_slugs(self) -> list[str]:
        return list(self._registry().list_slugs())

    def get_descriptor(self, slug: str) -> ToolDescriptor | None:
        reg = self._registry()
        cls = reg.get(slug)
        if not cls:
            return None
        return ToolDescriptor(
            slug=slug,
            description=getattr(cls, "description", "") or "",
            config_schema=getattr(cls, "config_schema", {}) or {},
        )

    def create_instance(self, slug: str, *, config: dict | None = None) -> Any:
        return self._registry().create(slug, config=config)

    def list_all(self) -> list[ToolDescriptor]:
        descriptors = []
        for cls in self._registry().all_detectors():
            slug = getattr(cls, "slug", "")
            descriptors.append(
                ToolDescriptor(
                    slug=slug,
                    description=getattr(cls, "description", "") or "",
                    config_schema=getattr(cls, "config_schema", {}) or {},
                )
            )
        return descriptors
