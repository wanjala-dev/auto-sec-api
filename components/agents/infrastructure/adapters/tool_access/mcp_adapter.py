"""MCP-based tool access adapter.

Delegates tool operations to a Model Context Protocol server.
This is the adapter for tools whose ``access_strategy`` is
``ToolAccessStrategy.MCP``.

The ``access_config`` on the Tool AR specifies the MCP server::

    access_config = {
        "server_name": "budget-mcp",
        "tool_name": "list_budgets",
        "server_url": "http://localhost:8080",
        "auth": {"type": "bearer", "token_env": "MCP_BUDGET_TOKEN"},
    }
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List

from components.agents.application.ports.tool_access_port import ToolAccessPort

logger = logging.getLogger(__name__)


class McpToolAccessAdapter(ToolAccessPort):
    """Executes tool operations via MCP protocol calls."""

    def execute(
        self,
        *,
        operation: str,
        workspace_id: str,
        params: Dict[str, Any],
        access_config: Dict[str, Any],
    ) -> Any:
        server_url = access_config.get("server_url")
        tool_name = access_config.get("tool_name")
        if not server_url or not tool_name:
            raise ValueError(
                "MCP access_config must specify 'server_url' and 'tool_name'"
            )

        # Build MCP tool call payload
        payload = {
            "tool": tool_name,
            "arguments": {
                "operation": operation,
                "workspace_id": workspace_id,
                **params,
            },
        }

        import httpx

        auth_config = access_config.get("auth", {})
        headers = {"Content-Type": "application/json"}
        if auth_config.get("type") == "bearer":
            import os

            token = os.environ.get(auth_config.get("token_env", ""), "")
            if token:
                headers["Authorization"] = f"Bearer {token}"

        response = httpx.post(
            f"{server_url}/tools/call",
            json=payload,
            headers=headers,
            timeout=30.0,
        )
        response.raise_for_status()
        return response.json()

    def supports_operation(self, operation: str) -> bool:
        # MCP tools support arbitrary operations — the server decides
        return True

    def list_operations(self) -> List[str]:
        return ["*"]  # MCP tools are generic

    def health_check(self, access_config: Dict[str, Any]) -> bool:
        server_url = access_config.get("server_url")
        if not server_url:
            return False
        try:
            import httpx

            response = httpx.get(f"{server_url}/health", timeout=5.0)
            return response.status_code == 200
        except Exception:
            return False
