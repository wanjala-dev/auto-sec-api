"""Port: read the workspace-brand fields a newsletter draft needs.

The workspace is another bounded context. Rather than the content
application layer reaching into ``workspaces`` persistence directly (a C3
cross-context read done through the ORM), it asks through this port; the
adapter in ``content/infrastructure/adapters/`` owns the sanctioned ORM read
and returns a frozen ``WorkspaceProfile`` value object.
"""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from components.content.domain.value_objects.workspace_profile import (
    WorkspaceProfile,
)


class WorkspaceProfilePort(Protocol):
    def get_profile(self, *, workspace_id: UUID) -> WorkspaceProfile:
        """Return the workspace's newsletter-relevant brand fields.

        Best-effort: a missing workspace or read error returns a blank
        ``WorkspaceProfile`` rather than raising — a newsletter draft must
        never fail because a brand field couldn't be resolved."""
        ...
