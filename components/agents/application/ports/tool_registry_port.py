"""Port for the AI tool/detector registry.

Abstracts the slug-based registration pattern so the application layer
can discover, instantiate, and list tools/detectors without depending
on the concrete registry implementation or its imports.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ToolDescriptor:
    """Metadata for a registered tool or detector."""
    slug: str = ""
    description: str = ""
    config_schema: dict = field(default_factory=dict)


class ToolRegistryPort(ABC):
    """Abstract contract for tool/detector registration and lookup."""

    @abstractmethod
    def list_slugs(self) -> list[str]:
        """Return all registered tool slugs."""
        ...

    @abstractmethod
    def get_descriptor(self, slug: str) -> ToolDescriptor | None:
        """Return metadata for a registered tool, or None if not found."""
        ...

    @abstractmethod
    def create_instance(self, slug: str, *, config: dict | None = None) -> Any:
        """Instantiate a tool/detector by slug.

        Raises KeyError if the slug is not registered.
        """
        ...

    @abstractmethod
    def list_all(self) -> list[ToolDescriptor]:
        """Return descriptors for all registered tools."""
        ...
