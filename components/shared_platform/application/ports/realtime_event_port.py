"""Realtime event port — the application's contract for publishing
events to the WebSocket transport (Phase 7.1).

Every long-running operation (agent runs, document uploads, budget /
income imports) publishes a ``resource.event`` envelope through this
port. Subscribed consumers (per-resource detail stream, per-workspace
activity feed) receive the envelope and forward it to the connected
client.

The envelope shape is stable — adding a new resource_type just means
a new publisher; no consumer or transport change required.

See ``docs/plans/REALTIME_OBSERVABILITY_PLAN.md`` Phase 7.1.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Mapping, Optional


class RealtimeEventPort(ABC):
    """Publish ``resource.event`` envelopes to the realtime layer."""

    @abstractmethod
    def publish(
        self,
        *,
        workspace_id: str,
        resource_type: str,
        resource_id: str,
        event_name: str,
        status: str,
        progress_percent: int = 0,
        payload: Optional[Mapping[str, object]] = None,
    ) -> None:
        """Publish a single event envelope.

        Parameters
        ----------
        workspace_id:
            Workspace the event belongs to. Drives the workspace
            activity feed group.
        resource_type:
            Stable identifier for the resource family (e.g.
            ``"agent_run"``, ``"document_upload"``).
        resource_id:
            Stable id of the specific resource instance (e.g. plan_id
            for an agent run).
        event_name:
            Lifecycle marker — ``"started"``, ``"progress"``,
            ``"tool_call"``, ``"completed"``, ``"failed"``, ``"token"``,
            etc. Free-form per resource_type.
        status:
            Current run status — ``"pending"``, ``"running"``,
            ``"completed"``, ``"failed"``.
        progress_percent:
            0-100. ``0`` for events that don't carry progress.
        payload:
            Resource-specific keys. Kept JSON-serialisable.
        """

    def publish_to_sponsor_feed(
        self,
        *,
        user_id: str,
        event_name: str,
        payload: Optional[Mapping[str, object]] = None,
        workspace_id: str = "",
    ) -> None:
        """Publish a donor-private transparency event to ONE donor's feed.

        Donor-scoped (``sponsor.<user_id>.feed``), unlike ``publish`` which
        fans out to workspace-visible groups — a sponsor must see only
        their own money move. ``event_name`` is the typed feed event
        (``donation_received``, ``sponsorship_charged``, ``funds_spent``,
        ``balance_updated``); ``payload`` carries amount/currency/recipient/
        remaining etc. ``workspace_id`` is informational (which org).

        Default no-op so non-realtime adapters (NoOp, test doubles) stay
        valid; the Channels adapter overrides it.
        """
        return None
