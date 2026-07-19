"""Cross-context journey: a sponsor browses recipients and donation history.

This is the canonical multi-context flow — it touches identity (auth + me/summary),
workspace (list + setup), and sponsorship (recipients + donations) in a realistic
order. The journey would mislead if owned by any one context's scenario file.

Read-only. No checkout. No writes.
"""
from __future__ import annotations

import logging

from locust import SequentialTaskSet, task

from tests.load.base_users import AuthenticatedHttpUser
from tests.load.config import settings

logger = logging.getLogger(__name__)


class SponsorBrowseTaskSet(SequentialTaskSet):
    """One pass of: me/summary → list workspaces → workspace setup → recipients → donations."""

    @task
    def me_summary(self) -> None:
        self.user.authed("get", "/identity/me/summary/", name="journey:/identity/me/summary/")

    @task
    def list_workspaces(self) -> None:
        response = self.user.authed("get", "/workspaces/", name="journey:/workspaces/")
        # The configured LOAD_SMOKE_WORKSPACE_ID always wins. /workspaces/ is a
        # directory that includes workspaces the smoke user is NOT a member of,
        # so blindly adopting results[0] used to clobber the configured id and
        # produce correct-RBAC 403s on the member-only tasks below.
        if settings.smoke_workspace_id:
            return
        if response.status_code == 200:
            try:
                payload = response.json()
                results = payload.get("results", payload) if isinstance(payload, dict) else payload
                if isinstance(results, list) and results:
                    self.user._workspace_id = str(results[0].get("id") or results[0].get("uuid"))
            except (ValueError, KeyError, TypeError):
                logger.exception("journey: list_workspaces failed to parse payload")

    @task
    def setup_status(self) -> None:
        ws = settings.smoke_workspace_id or getattr(self.user, "_workspace_id", None)
        if not ws:
            return
        self.user.authed(
            "get",
            f"/workspaces/{ws}/setup-status/",
            name="journey:/workspaces/[id]/setup-status/",
        )

    @task
    def list_recipients(self) -> None:
        ws = settings.smoke_workspace_id or getattr(self.user, "_workspace_id", None)
        if not ws:
            return
        self.user.authed(
            "get",
            f"/sponsorship/recipients/{ws}/",
            name="journey:/sponsorship/recipients/[workspace]/",
        )

    @task
    def list_donations(self) -> None:
        ws = settings.smoke_workspace_id or getattr(self.user, "_workspace_id", None)
        if not ws:
            return
        self.user.authed(
            "get",
            f"/sponsorship/donations/{ws}/",
            name="journey:/sponsorship/donations/[workspace]/",
        )

    @task
    def end(self) -> None:
        # Mark the iteration complete so Locust picks the user back up at the start.
        self.interrupt(reschedule=True)


class SponsorBrowseJourneyUser(AuthenticatedHttpUser):
    """Composes the SponsorBrowseTaskSet end-to-end. Higher weight in journeys."""

    weight = 5
    tasks = [SponsorBrowseTaskSet]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._workspace_id: str | None = None
