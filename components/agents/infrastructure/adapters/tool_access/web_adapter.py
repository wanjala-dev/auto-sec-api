"""Web/HTTP-based tool access adapter.

Delegates tool operations to an external REST API.
This is the adapter for tools whose ``access_strategy`` is
``ToolAccessStrategy.WEB``.

The ``access_config`` on the Tool AR specifies the API endpoint::

    access_config = {
        "base_url": "https://api.example.com/v1",
        "auth": {"type": "api_key", "header": "X-API-Key", "key_env": "EXAMPLE_API_KEY"},
        "operations": {
            "list":   {"method": "GET",  "path": "/budgets"},
            "get":    {"method": "GET",  "path": "/budgets/{id}"},
            "create": {"method": "POST", "path": "/budgets"},
        }
    }
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List

from components.agents.application.ports.tool_access_port import ToolAccessPort

logger = logging.getLogger(__name__)


class WebToolAccessAdapter(ToolAccessPort):
    """Executes tool operations via HTTP API calls."""

    def execute(
        self,
        *,
        operation: str,
        workspace_id: str,
        params: Dict[str, Any],
        access_config: Dict[str, Any],
    ) -> Any:
        base_url = access_config.get("base_url", "").rstrip("/")
        if not base_url:
            raise ValueError("Web access_config must specify 'base_url'")

        operations_map = access_config.get("operations", {})
        op_config = operations_map.get(operation)
        if not op_config:
            raise ValueError(
                f"No endpoint mapped for operation {operation!r}"
            )

        method = op_config.get("method", "GET").upper()
        path = op_config.get("path", "/")

        # Substitute path parameters from params
        for key, value in params.items():
            path = path.replace(f"{{{key}}}", str(value))

        url = f"{base_url}{path}"
        headers = self._build_headers(access_config)

        import httpx

        if method == "GET":
            response = httpx.get(url, params=params, headers=headers, timeout=30.0)
        elif method in ("POST", "PUT", "PATCH"):
            response = httpx.request(
                method, url, json=params, headers=headers, timeout=30.0
            )
        elif method == "DELETE":
            response = httpx.delete(url, headers=headers, timeout=30.0)
        else:
            raise ValueError(f"Unsupported HTTP method: {method}")

        response.raise_for_status()
        return response.json() if response.content else None

    def supports_operation(self, operation: str) -> bool:
        return operation in ("list", "get", "create", "update", "delete", "search")

    def list_operations(self) -> List[str]:
        return ["list", "get", "create", "update", "delete", "search"]

    def health_check(self, access_config: Dict[str, Any]) -> bool:
        base_url = access_config.get("base_url", "")
        if not base_url:
            return False
        try:
            import httpx

            response = httpx.get(base_url, timeout=5.0)
            return response.status_code < 500
        except Exception:
            return False

    @staticmethod
    def _build_headers(access_config: Dict[str, Any]) -> Dict[str, str]:
        headers: Dict[str, str] = {"Content-Type": "application/json"}
        auth = access_config.get("auth", {})
        auth_type = auth.get("type", "")

        if auth_type == "api_key":
            header_name = auth.get("header", "Authorization")
            key = os.environ.get(auth.get("key_env", ""), "")
            if key:
                headers[header_name] = key
        elif auth_type == "bearer":
            token = os.environ.get(auth.get("token_env", ""), "")
            if token:
                headers["Authorization"] = f"Bearer {token}"

        return headers
