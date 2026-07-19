from __future__ import annotations

from components.recycle_bin.application.ports.soft_delete_port import SoftDeletePort
from components.shared_kernel.domain.errors import ConfigurationError


class SoftDeleteProvider:
    """Registry that maps entity_type strings to SoftDeletePort adapters."""

    def __init__(self) -> None:
        self._adapters: dict[str, SoftDeletePort] = {}

    def register(self, adapter: SoftDeletePort) -> None:
        self._adapters[adapter.entity_type()] = adapter

    def get_adapter(self, entity_type: str) -> SoftDeletePort:
        try:
            return self._adapters[entity_type]
        except KeyError:
            raise ConfigurationError(f"No SoftDeletePort adapter registered for entity type: {entity_type}")

    def supported_types(self) -> list[str]:
        return list(self._adapters.keys())
