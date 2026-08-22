"""Port: read and write a workspace's autonomy mode (outbound / driven).

``Workspace.autonomy_mode`` is the workspace context's OWN data, so the
workspace context owns both sides of it (architecture-manifesto Rule 2 /
architecture-skill C2 — a component never changes data it does not own). This
port is the owning-context surface behind which the ORM lives; the agents
context reads through the workspace's application layer rather than touching a
workspace model.

Read and write sit on ONE port on purpose. They are the same field and the same
ownership question, and splitting them would invite a second read path that
skips whatever the write path guarantees.

No Django imports — depends only on the standard library.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class WorkspaceAutonomyResult:
    """Outcome of a change request against ``Workspace.autonomy_mode``.

    ``instance`` is the workspace ORM object — carried back so the owning use
    case can hand it to the audit provider's ``log_field_change``, which keys
    the entry on the changed instance. It never leaves the workspace context.
    """

    instance: Any
    previous: str
    changed: bool


class WorkspaceAutonomyStorePort(ABC):
    """Read and set ``Workspace.autonomy_mode`` for one workspace."""

    @abstractmethod
    def get_mode(self, workspace_id: str) -> str | None:
        """The stored mode, or ``None`` when the workspace does not exist.

        Returning ``None`` rather than a default matters: "this workspace is on
        ASSIST" and "there is no such workspace" are different answers, and a
        caller that cannot tell them apart will enforce a policy for a tenant
        that does not exist.
        """
        ...

    @abstractmethod
    def set_mode(self, workspace_id: str, *, mode: str) -> WorkspaceAutonomyResult | None:
        """Set the mode, persisting only when the value actually changes.

        Returns a :class:`WorkspaceAutonomyResult` (with the previous value and
        whether a write happened), or ``None`` when the workspace does not exist.
        """
        ...
