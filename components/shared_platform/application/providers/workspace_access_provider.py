"""Provider for the WorkspaceAccessPort used by search.

Matches the existing ``search_provider`` pattern: a small composition
root that returns the wired adapter. Kept minimal — there is only one
adapter today (ORM), but the indirection keeps the controller free of
adapter imports and makes future swaps (e.g., a cache-backed adapter)
trivial.
"""

from __future__ import annotations

from functools import lru_cache

from components.shared_platform.application.ports.workspace_access_port import (
    WorkspaceAccessPort,
)


@lru_cache(maxsize=1)
def get_workspace_access_adapter() -> WorkspaceAccessPort:
    from components.shared_platform.infrastructure.adapters.orm_workspace_access_adapter import (
        OrmWorkspaceAccessAdapter,
    )

    return OrmWorkspaceAccessAdapter()
