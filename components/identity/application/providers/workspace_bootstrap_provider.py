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


_default = WorkspaceBootstrapProvider()


def get_workspace_bootstrap_provider() -> WorkspaceBootstrapProvider:
    return _default
