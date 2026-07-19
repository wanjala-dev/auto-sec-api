"""Budgeting surface — budget list per workspace + dashboard reads."""
from __future__ import annotations

import logging

from locust import task

from tests.load.base_users import AuthenticatedHttpUser
from tests.load.config import settings

logger = logging.getLogger(__name__)


class BudgetingLoadUser(AuthenticatedHttpUser):
    weight = 2

    def on_start(self) -> None:
        super().on_start()
        self._workspace_id = settings.smoke_workspace_id or self._discover_workspace_id()

    def _discover_workspace_id(self) -> str | None:
        response = self.authed("get", "/workspaces/", name="/workspaces/ (discover)")
        if response.status_code != 200:
            return None
        try:
            payload = response.json()
            results = payload.get("results", payload) if isinstance(payload, dict) else payload
            if isinstance(results, list) and results:
                return str(results[0].get("id") or results[0].get("uuid"))
        except (ValueError, KeyError, TypeError):
            logger.exception("budgeting: workspace discovery failed")
        return None

    @task(3)
    def workspace_budgets(self) -> None:
        if not self._workspace_id:
            return
        # Note: /budget/<str:workspace> has NO trailing slash per components/budgeting/api/urls.py.
        self.authed(
            "get",
            f"/budget/{self._workspace_id}",
            name="/budget/[workspace]",
        )

    @task(2)
    def budget_dashboard(self) -> None:
        if not self._workspace_id:
            return
        self.authed(
            "get",
            f"/budget/dashboard/{self._workspace_id}/",
            name="/budget/dashboard/[workspace]/",
        )
