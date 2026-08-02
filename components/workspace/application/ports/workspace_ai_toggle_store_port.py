"""Port: persist the workspace AI-teammate enabled flag (outbound / driven).

``Workspace.ai_teammate_enabled`` is the workspace context's OWN data, so the
workspace context owns writes to it (architecture-manifesto Rule 2 /
architecture-skill C2 — a component never changes data it does not own). This
port is the owning-context surface behind which the ORM write lives; the
:class:`SetWorkspaceAiEnabledUseCase` depends on it, and another context (the
agents AI kill switch) delegates to that use case rather than writing the field
itself.

No Django imports — depends only on the standard library.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class WorkspaceAiToggleResult:
    """Outcome of a flip request against ``Workspace.ai_teammate_enabled``.

    ``instance`` is the workspace ORM object — carried back so the owning use
    case can hand it to the audit provider's ``log_field_change`` (which keys the
    audit entry on the changed instance). It stays inside the workspace context.
    """

    instance: Any
    previous: bool
    changed: bool


class WorkspaceAiToggleStorePort(ABC):
    """Set ``Workspace.ai_teammate_enabled`` for one workspace."""

    @abstractmethod
    def set_ai_enabled(self, workspace_id: str, *, enabled: bool) -> WorkspaceAiToggleResult | None:
        """Flip the flag to *enabled*, persisting only when the value changes.

        Returns a :class:`WorkspaceAiToggleResult` (with the previous value and
        whether a write happened), or ``None`` when the workspace does not exist.
        """
        ...
