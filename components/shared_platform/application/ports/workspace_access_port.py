"""Port describing viewer → workspace access lookups needed by search.

Defined in ``shared_platform`` because search is platform-wide and must
not reach into another bounded context's infrastructure to discover
which workspaces the caller can see. Concrete adapters live in
``shared_platform/infrastructure/adapters/`` and read the Workspace /
WorkspaceMembership ORM models directly.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class WorkspaceAccessPort(ABC):
    """Secondary/driven port: what workspaces can a viewer read?"""

    @abstractmethod
    def accessible_workspace_ids(self, *, user_id: Any) -> set[str]:
        """Return the set of workspace ids the viewer can see.

        Callers should treat staff/superuser bypass as policy on the
        caller side; this port answers the per-user question only.
        """
        ...
