"""Port: read the agents context's OWN ``ai.*`` rows the governance report needs.

``ai_governance_service`` computes the AI-SPM report from rows that already
exist. Its CROSS-context reads (the ``project`` HITL ledger, the ``integrations``
GitHub credential surface, the ``workspace`` kill-switch toggle) are already
routed through ports (burndown PR-6). What remained were its SAME-context ``ai.*``
reads — deep-run activity, per-agent capability config, the AI service principals,
and the kill-switch agent/run inventory — read inline off
``infrastructure.persistence.ai`` from the application layer (Rule-2 violation).
This port is that same-context read seam; the ORM lives in the adapter.

The port returns plain dicts/lists the ``compute_*`` functions already consume, so
the deterministic aggregation (risk resolution, source classification, honesty
flags) stays in the application layer. The one exception is the per-agent audit
history, which needs the ORM instance to reach the audit provider — the adapter
gathers it and returns it as ``grant_audit_entries`` on each agent row.

All reads are workspace-scoped (tenant isolation) and read-only.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class AiActivityRows:
    """Raw run + tool-log rows for ``compute_ai_activity``.

    ``run_rows`` = ``{"id", "status", "user_id"}`` per DeepRun in the window;
    ``tool_rows`` = ``{"agent_type", "tool_name"}`` per ``tool_observation``
    DeepRunLog in the window; ``service_user_ids`` = the workspace's AI service
    principals (``AITeammateProfile.user_id`` set) used to classify a run as
    detector-dispatched vs interactive. Risk resolution + source classification
    stay in the application layer (``ai_governance_service``).
    """

    run_rows: list[dict[str, Any]] = field(default_factory=list)
    tool_rows: list[dict[str, Any]] = field(default_factory=list)
    service_user_ids: frozenset[str] = frozenset()


@dataclass(frozen=True)
class KillSwitchInventory:
    """The agents-owned facts ``compute_kill_switch_status`` needs beyond the
    workspace toggle (which is read through ``WorkspaceQueryPort``).

    ``teammate_profile`` mirrors the prior inline shape
    (``{"status", "is_enabled"}`` or ``None``); ``agent_rows`` = ``{"agent_id",
    "agent_type", "status"}`` per Agent; ``in_flight_deep_runs`` counts pending +
    running deep runs.
    """

    teammate_profile: dict[str, Any] | None
    agent_rows: list[dict[str, Any]] = field(default_factory=list)
    in_flight_deep_runs: int = 0


class AiGovernanceReadPort(ABC):
    """Read the agents-owned ``ai.*`` rows the governance report aggregates."""

    @abstractmethod
    def collect_ai_activity(self, *, workspace_id: str, window_start: datetime) -> AiActivityRows:
        """Deep-run + tool-observation activity for a workspace in the window,
        plus the AI service-principal user ids for source classification.
        """

    @abstractmethod
    def collect_capability_agent_rows(self, *, workspace_id: str) -> list[dict[str, Any]]:
        """Per-agent capability inventory for a workspace, as the rows
        ``compute_capability_grants`` consumes: ``{"agent_id", "agent_type",
        "status", "capabilities", "power_flags", "grant_audit_entries"}``. The
        adapter resolves ``power_flags`` from the allowlisted config keys and
        gathers ``grant_audit_entries`` from the audit context (best-effort).
        """

    @abstractmethod
    def collect_kill_switch_inventory(self, *, workspace_id: str) -> KillSwitchInventory:
        """The teammate profile, per-agent status inventory, and in-flight
        deep-run count for a workspace's kill-switch report.
        """
