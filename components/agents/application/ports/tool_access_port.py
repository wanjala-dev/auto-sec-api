"""Intra-context port for tool data access strategies.

This is an **internal** port (within the agents bounded context) that
abstracts HOW a tool accesses external resources.  Infrastructure
adapters implement this port for each access strategy:

- ``OrmToolAccessAdapter``  — Django ORM queries
- ``McpToolAccessAdapter``  — Model Context Protocol servers
- ``WebToolAccessAdapter``  — HTTP/REST API calls
- ``FileToolAccessAdapter`` — Local filesystem reads/writes
- ``CachingToolAccessAdapter`` — Decorator that wraps any adapter with caching

The ``ToolAccessResolver`` in the application layer picks the correct
adapter based on the Tool AR's ``access_strategy`` field.

This is NOT a cross-context port — it does not cross bounded context
boundaries.  Cross-context data flows go through facades.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class ToolAccessPort(ABC):
    """Abstract interface for executing tool operations against a data source."""

    @abstractmethod
    def execute(
        self,
        *,
        operation: str,
        workspace_id: str,
        params: Dict[str, Any],
        access_config: Dict[str, Any],
    ) -> Any:
        """Execute a tool operation and return the result.

        Parameters
        ----------
        operation :
            The operation name (e.g., "list", "get", "create", "update",
            "search", "summarize").
        workspace_id :
            The workspace context for the operation.
        params :
            Operation-specific parameters from the LLM tool call.
        access_config :
            Strategy-specific configuration from the Tool AR's
            ``access_config`` field.
        """
        ...

    def execute_batch(
        self,
        *,
        workspace_id: str,
        items: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Execute multiple operations in a single round-trip.

        Default implementation falls back to sequential ``execute()``
        calls.  Adapters that support true batching (e.g. ORM within
        a single transaction, MCP with multiplexed calls) should
        override this for efficiency.

        Parameters
        ----------
        workspace_id :
            The workspace context for all operations in the batch.
        items :
            List of dicts, each containing: operation, params, access_config.

        Returns
        -------
        List of dicts, each containing: success (bool), result or error.
        """
        results: List[Dict[str, Any]] = []
        for item in items:
            try:
                result = self.execute(
                    operation=item.get("operation", ""),
                    workspace_id=workspace_id,
                    params=item.get("params", {}),
                    access_config=item.get("access_config", {}),
                )
                results.append({"success": True, "result": result})
            except Exception as exc:
                results.append({"success": False, "error": str(exc)})
        return results

    @abstractmethod
    def supports_operation(self, operation: str) -> bool:
        """Return True if this adapter can handle *operation*."""
        ...

    @abstractmethod
    def list_operations(self) -> List[str]:
        """Return all operations this adapter supports."""
        ...

    @abstractmethod
    def health_check(self, access_config: Dict[str, Any]) -> bool:
        """Return True if the underlying data source is reachable."""
        ...
