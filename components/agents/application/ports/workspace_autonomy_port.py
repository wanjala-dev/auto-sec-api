"""Port: read a workspace's autonomy mode from the agents context (ADR 0035 D6).

``Workspace.autonomy_mode`` is the *workspace* context's data. The tool gate
enforces it but must not read a workspace model directly
(architecture-manifesto Rule 2 / architecture-skill C2). The gate depends on this
port; the adapter delegates to the workspace context's application surface.

Read-only on purpose. The agents context has no business changing how much
autonomy a customer granted it.

No Django imports — depends only on the standard library.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class WorkspaceAutonomyPort(ABC):
    @abstractmethod
    def get_mode(self, *, workspace_id: str) -> str | None:
        """The workspace's configured mode, or ``None`` when there is no such workspace.

        Implementations MUST let read failures propagate rather than returning
        ``None`` for them. The two are opposite in consequence: "no workspace"
        is a run with nothing to govern, while "the setting could not be read"
        means we do not know what this customer permitted — and the caller
        resolves that to UNKNOWN, which holds writes. Collapsing a failed read
        into ``None`` would fail OPEN on the one control whose whole purpose is
        answering "may the AI change things in my account".
        """
        ...
