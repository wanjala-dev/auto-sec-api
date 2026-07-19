"""ORM-based tool access adapter.

Delegates to the existing ``ToolRepositoryRegistry`` which wraps
Django ORM queries behind repository ports.  This is the adapter for
tools whose ``access_strategy`` is ``ToolAccessStrategy.ORM``.

The ``access_config`` on the Tool AR specifies which repository to use::

    access_config = {
        "repository": "budget",   # key in ToolRepositoryRegistry
        "operations": {
            "list": "list_for_workspace",
            "get":  "get_by_id",
            "create": "create",
        }
    }
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from components.agents.application.ports.tool_access_port import ToolAccessPort

logger = logging.getLogger(__name__)


class OrmToolAccessAdapter(ToolAccessPort):
    """Executes tool operations via Django ORM repositories."""

    def execute(
        self,
        *,
        operation: str,
        workspace_id: str,
        params: Dict[str, Any],
        access_config: Dict[str, Any],
    ) -> Any:
        from components.agents.infrastructure.adapters.langchain.tools._repos import repos

        repo_name = access_config.get("repository")
        if not repo_name:
            raise ValueError("ORM access_config must specify 'repository'")

        repo = getattr(repos, repo_name, None)
        if repo is None:
            raise ValueError(f"Unknown repository: {repo_name!r}")

        operations_map = access_config.get("operations", {})
        method_name = operations_map.get(operation)
        if not method_name:
            raise ValueError(
                f"No method mapped for operation {operation!r} "
                f"in repository {repo_name!r}"
            )

        method = getattr(repo, method_name, None)
        if method is None:
            raise ValueError(
                f"Repository {repo_name!r} has no method {method_name!r}"
            )

        # Inject workspace_id for list-style operations
        if "workspace_id" in method.__code__.co_varnames:
            return method(workspace_id=workspace_id, **params)
        return method(**params)

    def supports_operation(self, operation: str) -> bool:
        return operation in ("list", "get", "create", "update", "search", "summarize")

    def list_operations(self) -> List[str]:
        return ["list", "get", "create", "update", "search", "summarize"]

    def health_check(self, access_config: Dict[str, Any]) -> bool:
        try:
            from django.db import connection

            connection.ensure_connection()
            return True
        except Exception:
            return False
