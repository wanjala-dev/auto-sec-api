"""Resolves the correct ToolAccessPort adapter for a Tool entity.

This is a domain service in the application layer that maps a Tool's
``access_strategy`` to the correct infrastructure adapter.  It's wired
in the composition root (``AIProvider``).
"""

from __future__ import annotations

from typing import Dict

from components.agents.domain.entities.tool_entity import ToolEntity
from components.agents.domain.enums import ToolAccessStrategy
from components.agents.application.ports.tool_access_port import ToolAccessPort


class ToolAccessResolver:
    """Strategy pattern: resolves access_strategy → ToolAccessPort adapter."""

    def __init__(self) -> None:
        self._adapters: Dict[str, ToolAccessPort] = {}

    def register(self, strategy: str, adapter: ToolAccessPort) -> None:
        """Register an adapter for a given access strategy."""
        if strategy not in ToolAccessStrategy.ALL:
            from components.shared_kernel.domain.errors import ValidationError as DomainValidationError

            raise DomainValidationError(
                f"Unknown access strategy {strategy!r}. "
                f"Must be one of: {', '.join(ToolAccessStrategy.ALL)}"
            )
        self._adapters[strategy] = adapter

    def resolve(self, tool: ToolEntity) -> ToolAccessPort:
        """Return the adapter for *tool*'s access strategy."""
        adapter = self._adapters.get(tool.access_strategy)
        if adapter is None:
            raise KeyError(
                f"No adapter registered for access strategy "
                f"{tool.access_strategy!r}. "
                f"Registered: {list(self._adapters.keys())}"
            )
        return adapter

    def has_adapter(self, strategy: str) -> bool:
        return strategy in self._adapters
