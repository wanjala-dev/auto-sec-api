"""BatchToolExecution — value object for grouping compatible tool calls.

When an agent needs to invoke multiple tools in a single reasoning step,
compatible calls (same access strategy, same workspace) can be batched
to reduce round-trips: one DB transaction instead of five for ORM tools,
one MCP session for multiple MCP calls, etc.

This is a pure domain value object — no ORM, no framework imports.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from uuid import UUID


@dataclass(frozen=True)
class BatchItem:
    """A single operation within a batch."""

    tool_id: UUID
    operation: str
    params: Dict[str, Any] = field(default_factory=dict)
    access_config: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class BatchResult:
    """Result of a single item within a batch."""

    tool_id: UUID
    operation: str
    success: bool
    result: Optional[Any] = None
    error: Optional[str] = None
    execution_time_ms: int = 0


@dataclass(frozen=True)
class BatchToolExecution:
    """Immutable value object representing a group of compatible tool calls.

    Invariants:
    - All items must share the same ``access_strategy``.
    - All items must share the same ``workspace_id``.
    - A batch must contain at least one item.
    """

    workspace_id: UUID
    access_strategy: str
    items: List[BatchItem] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.items:
            raise ValueError("BatchToolExecution must contain at least one item")

    @property
    def size(self) -> int:
        return len(self.items)

    @property
    def operation_names(self) -> List[str]:
        return [item.operation for item in self.items]

    @property
    def tool_ids(self) -> List[UUID]:
        return [item.tool_id for item in self.items]

    @classmethod
    def from_calls(
        cls,
        *,
        workspace_id: UUID,
        access_strategy: str,
        calls: List[Dict[str, Any]],
    ) -> "BatchToolExecution":
        """Build a batch from a list of raw call dicts.

        Each dict must have: tool_id, operation, params, access_config.
        """
        items = [
            BatchItem(
                tool_id=call["tool_id"],
                operation=call["operation"],
                params=call.get("params", {}),
                access_config=call.get("access_config", {}),
            )
            for call in calls
        ]
        return cls(
            workspace_id=workspace_id,
            access_strategy=access_strategy,
            items=items,
        )

    @staticmethod
    def group_by_strategy(
        calls: List[Dict[str, Any]],
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Partition a flat list of call dicts by access_strategy.

        Returns a dict mapping strategy → list of calls suitable for
        building individual ``BatchToolExecution`` instances.
        """
        groups: Dict[str, List[Dict[str, Any]]] = {}
        for call in calls:
            strategy = call.get("access_strategy", "")
            groups.setdefault(strategy, []).append(call)
        return groups
