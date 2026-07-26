"""Provider for the workspace-bootstrap check.

Controllers consume this provider instead of importing the concrete
adapter so the API layer's import graph stays free of identity
infrastructure references.
"""

from __future__ import annotations

from typing import Any


class WorkspaceBootstrapProvider:
    def should_bootstrap_workspace(self, *args, **kwargs) -> bool:
        from components.identity.infrastructure.adapters.workspace_bootstrap import (
            should_bootstrap_workspace,
        )

        return should_bootstrap_workspace(*args, **kwargs)

    def preferred_workspace_for_user(self, *args, **kwargs) -> Any:
        from components.identity.infrastructure.adapters.workspace_bootstrap import (
            _preferred_workspace_for_user,
        )

        return _preferred_workspace_for_user(*args, **kwargs)

    def create_bootstrap_workspace(self, *args, **kwargs) -> Any:
        from components.identity.infrastructure.adapters.workspace_bootstrap import (
            _create_bootstrap_workspace,
        )

        return _create_bootstrap_workspace(*args, **kwargs)

    def sync_profile_context(self, *args, **kwargs) -> Any:
        from components.identity.infrastructure.adapters.workspace_bootstrap import (
            _sync_profile_context,
        )

        return _sync_profile_context(*args, **kwargs)

    def ensure_personal_workspace(self, *args, **kwargs) -> Any:
        from components.identity.infrastructure.adapters.workspace_bootstrap import (
            ensure_personal_workspace,
        )

        return ensure_personal_workspace(*args, **kwargs)


_default = WorkspaceBootstrapProvider()


def get_workspace_bootstrap_provider() -> WorkspaceBootstrapProvider:
    return _default
