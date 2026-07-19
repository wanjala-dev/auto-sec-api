"""Workspace surface — list + setup-status reads.

Reads only. No workspace creation under load (would pollute demo DB).
"""
from __future__ import annotations

import logging

from locust import task

from tests.load.base_users import AuthenticatedHttpUser
from tests.load.config import settings

logger = logging.getLogger(__name__)


class WorkspaceLoadUser(AuthenticatedHttpUser):
    weight = 3

    def on_start(self) -> None:
        super().on_start()
        self._workspace_id = settings.smoke_workspace_id or self._discover_workspace_id()

    def _discover_workspace_id(self) -> str | None:
        """List workspaces and pick the first as a fallback when LOAD_SMOKE_WORKSPACE_ID is unset."""
        response = self.authed("get", "/workspaces/", name="/workspaces/ (discover)")
        if response.status_code != 200:
            logger.warning("workspace discovery failed status=%s", response.status_code)
            return None
        try:
            payload = response.json()
            results = payload.get("results", payload) if isinstance(payload, dict) else payload
            if isinstance(results, list) and results:
                return str(results[0].get("id") or results[0].get("uuid"))
        except (ValueError, KeyError, TypeError):
            logger.exception("workspace discovery: failed to parse payload")
        return None

    @task(5)
    def list_workspaces(self) -> None:
        self.authed("get", "/workspaces/", name="/workspaces/")

    @task(2)
    def setup_status(self) -> None:
        if not self._workspace_id:
            return
        self.authed(
            "get",
            f"/workspaces/{self._workspace_id}/setup-status/",
            name="/workspaces/[id]/setup-status/",
        )
