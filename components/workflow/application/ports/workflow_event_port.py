"""Port: Workflow event emission.

No Django imports — depends only on standard library.
Cross-context integration point: other bounded contexts call emit_workflow_event
via this port to trigger workflow automation without coupling to workflow internals.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class EmitWorkflowEventCommand:
    workspace_id: str
    source_type: str
    trigger_type: str
    payload: dict[str, Any] = field(default_factory=dict)
    source_id: str | None = None
    idempotency_key: str = ""


class WorkflowEventPort(abc.ABC):
    """Secondary port for emitting workflow events from other contexts."""

    @abc.abstractmethod
    def emit_event(self, *, command: EmitWorkflowEventCommand) -> None:
        """Persist a workflow event and enqueue processing after commit.

        Implementations should use the outbox pattern: write to the database
        inside the current transaction, then dispatch async processing on commit.
        """
        ...
