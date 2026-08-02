"""Port: flip a workspace's AI-teammate flag from the agents context.

``Workspace.ai_teammate_enabled`` is the *workspace* context's data. The agents
AI kill switch must not write it directly (architecture-manifesto Rule 2 /
architecture-skill C2 — a component never changes data it does not own). The
kill-switch use case depends on this port instead; the adapter delegates to the
workspace context's application surface, which performs the actual write. The
agents context never imports ``infrastructure.persistence.workspaces`` or any
workspace model.

No Django imports — depends only on the standard library.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class WorkspaceAiToggleOutcome:
    """What the workspace context reports back after a flip."""

    previous: bool
    changed: bool


class WorkspaceAiTogglePort(ABC):
    @abstractmethod
    def set_ai_enabled(
        self,
        *,
        workspace_id: str,
        enabled: bool,
        actor: Any,
        reason: str,
    ) -> WorkspaceAiToggleOutcome:
        """Set the workspace's ``ai_teammate_enabled`` flag (audited by the owner).

        Raises the workspace context's not-found error when the workspace does
        not exist. The owning write records the field-change audit; the caller
        supplies ``actor`` + ``reason`` for that record.
        """
        ...
