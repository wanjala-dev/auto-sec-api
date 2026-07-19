"""Tier 3 #14 — port for the per-workspace "latest event" query.

The index-freshness SLO needs to answer: for workspace W, when did
its most recent reindex-triggering event happen? The event sources
are spread across multiple bounded contexts (Workspace, Donation,
Recipient, Campaign, Grant, Project, Team, WorkspaceMembership), so
the application layer talks to a single port that hides the
multi-context query.

The port is one method on purpose. Bigger surface area would tempt
the adapter to leak domain-specific logic upward into the
application layer.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional


class WorkspaceEventLatestPort(ABC):
    """Resolve the latest reindex-triggering event for a workspace."""

    @abstractmethod
    def latest_event_time(
        self, *, workspace_id: str
    ) -> Optional[datetime]:
        """Return the most recent event timestamp, or None if the
        workspace has no events at all (a freshly-created workspace
        before any data lands).

        The implementation walks every model that has a signal-bridge
        wired in ``WorkspaceIndexSignalProvider``. Adding a new
        signal bridge requires adding the same model to this query —
        otherwise the SLO under-reports lag because the audit
        doesn't see the trigger source.
        """
        raise NotImplementedError
