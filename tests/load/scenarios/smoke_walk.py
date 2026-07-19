"""Sequential smoke walker — single VU, hits every smoke endpoint once, then quits.

Smoke testing convention: coverage > load. The walker spawns once, walks the
endpoint list in order, and tells the runner to quit. Exit code reflects
pass/fail per task.

Used by `make smoke` / `make smoke-demo` (LOAD_PROFILE=smoke). For any
heavier profile (avg/spike/stress/soak), the locustfile imports the
weighted per-context users + cross-context journey instead — different
mental model, different tool.

If login fails, AuthenticatedHttpUser.on_start() quits the runner with
exit code 1, so the smoke signal is preserved even when auth itself is
the broken thing.
"""
from __future__ import annotations

import logging
from typing import Any

from locust import SequentialTaskSet, between, task

from tests.load.base_users import AuthenticatedHttpUser
from tests.load.config import settings

logger = logging.getLogger(__name__)


def _extract_first_workspace_id(payload: Any) -> str | None:
    """Pick the first workspace id out of a /workspaces/ list response."""
    results = payload.get("results", payload) if isinstance(payload, dict) else payload
    if isinstance(results, list) and results:
        first = results[0]
        if isinstance(first, dict):
            return str(first.get("id") or first.get("uuid")) or None
    return None


class SmokeWalkTaskSet(SequentialTaskSet):
    """One ordered pass through the smoke surface. Tasks run in declaration order."""

    @task
    def t01_health_liveness(self) -> None:
        self.user.client.get("/api/health/", name="/api/health/")

    @task
    def t02_health_celery(self) -> None:
        self.user.client.get("/api/health/celery/", name="/api/health/celery/")

    @task
    def t03_schema(self) -> None:
        self.user.client.get("/api/schema/", name="/api/schema/")

    @task
    def t04_me_summary(self) -> None:
        self.user.authed("get", "/identity/me/summary/", name="/identity/me/summary/")

    @task
    def t05_list_workspaces(self) -> None:
        response = self.user.authed("get", "/workspaces/", name="/workspaces/")
        # The configured LOAD_SMOKE_WORKSPACE_ID always wins. /workspaces/ is a
        # directory that includes workspaces the smoke user is NOT a member of;
        # adopting results[0] used to clobber the configured id and produce
        # correct-RBAC 403s on the member-only tasks below (donations list).
        if settings.smoke_workspace_id:
            return
        if response.status_code == 200:
            try:
                ws_id = _extract_first_workspace_id(response.json())
                if ws_id:
                    self.user.workspace_id = ws_id
            except (ValueError, KeyError, TypeError):
                logger.exception("smoke: failed to parse /workspaces/ payload")

    @task
    def t06_setup_status(self) -> None:
        ws = self._workspace_id()
        if not ws:
            return
        self.user.authed(
            "get", f"/workspaces/{ws}/setup-status/",
            name="/workspaces/[id]/setup-status/",
        )

    @task
    def t07_recipients(self) -> None:
        ws = self._workspace_id()
        if not ws:
            return
        self.user.authed(
            "get", f"/sponsorship/recipients/{ws}/",
            name="/sponsorship/recipients/[workspace]/",
        )

    @task
    def t08_donations(self) -> None:
        ws = self._workspace_id()
        if not ws:
            return
        self.user.authed(
            "get", f"/sponsorship/donations/{ws}/",
            name="/sponsorship/donations/[workspace]/",
        )

    @task
    def t09_budget(self) -> None:
        ws = self._workspace_id()
        if not ws:
            return
        # Note: /budget/<workspace> has no trailing slash per components/budgeting/api/urls.py.
        self.user.authed(
            "get", f"/budget/{ws}",
            name="/budget/[workspace]",
        )

    @task
    def t10_budget_dashboard(self) -> None:
        ws = self._workspace_id()
        if not ws:
            return
        self.user.authed(
            "get", f"/budget/dashboard/{ws}/",
            name="/budget/dashboard/[workspace]/",
        )

    @task
    def t11_agents(self) -> None:
        self.user.authed("get", "/ai/agents/", name="/ai/agents/")

    @task
    def t12_token_refresh(self) -> None:
        # Force-expire the cached access token so _ensure_fresh_token issues a refresh.
        if self.user._tokens is not None:
            self.user._tokens.access_expiry_epoch_s = 0.0
        self.user._ensure_fresh_token()

    @task
    def t99_stop(self) -> None:
        # One pass is enough — exit cleanly so the smoke run ends with the right
        # code instead of waiting for the shape's run-time to elapse.
        self.user.environment.runner.quit()

    def _workspace_id(self) -> str | None:
        return settings.smoke_workspace_id or getattr(self.user, "workspace_id", None)


class SmokeWalkUser(AuthenticatedHttpUser):
    """Single-pass walker for `LOAD_PROFILE=smoke`. One VU, no wait between tasks."""

    weight = 1
    wait_time = between(0, 0)
    tasks = [SmokeWalkTaskSet]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.workspace_id: str | None = None
