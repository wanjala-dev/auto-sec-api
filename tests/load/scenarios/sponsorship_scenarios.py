"""Sponsorship surface — recipient + donation reads.

Reads ONLY. Donation checkout, sponsor checkout, and Stripe webhook routes are
forbidden under load (see `.claude/rules/load-testing.md` §6).
"""
from __future__ import annotations

import logging

from locust import task

from tests.load.base_users import AuthenticatedHttpUser
from tests.load.config import settings

logger = logging.getLogger(__name__)


class SponsorshipLoadUser(AuthenticatedHttpUser):
    weight = 4

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
            logger.exception("sponsorship: workspace discovery failed")
        return None

    @task(5)
    def list_recipients(self) -> None:
        if not self._workspace_id:
            return
        self.authed(
            "get",
            f"/sponsorship/recipients/{self._workspace_id}/",
            name="/sponsorship/recipients/[workspace]/",
        )

    @task(5)
    def list_donations(self) -> None:
        if not self._workspace_id:
            return
        self.authed(
            "get",
            f"/sponsorship/donations/{self._workspace_id}/",
            name="/sponsorship/donations/[workspace]/",
        )
