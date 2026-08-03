"""ORM adapter implementing :class:`AiGovernanceReadPort`.

Reads the agents-owned ``ai.*`` rows the governance report needs — deep-run
activity, per-agent capability config + audit history, the AI service principals,
and the kill-switch agent/run inventory — the exact queries
``ai_governance_service`` did inline, moved behind the port so the application
layer no longer imports persistence.

The per-agent audit history is gathered here (not in the application layer)
because it needs the ORM ``Agent`` instance to reach the audit provider; the
result is returned as ``grant_audit_entries`` on each row so the pure
``compute_capability_grants`` shaping stays framework-free.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from components.agents.application.ports.ai_governance_read_port import (
    AiActivityRows,
    AiGovernanceReadPort,
    KillSwitchInventory,
)

logger = logging.getLogger(__name__)

# Config keys that gate power beyond the capabilities map — mirrors the
# application service's allowlist (imported lazily to avoid an import cycle at
# module load; the constant is an application-layer policy, read here only).
_MAX_AUDIT_ENTRIES_PER_AGENT = 10


def _parse_iso(value: Any) -> datetime | None:
    """Defensive ISO/​datetime normalization (naive → UTC). Mirrors the
    application service's ``_parse_iso`` for the audit-entry timestamps."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


class OrmAiGovernanceReadRepository(AiGovernanceReadPort):
    def collect_ai_activity(self, *, workspace_id: str, window_start: datetime) -> AiActivityRows:
        from infrastructure.persistence.ai.agents.models import DeepRun, DeepRunLog
        from infrastructure.persistence.ai.models import AITeammateProfile

        workspace_id = str(workspace_id)
        service_user_ids = frozenset(
            str(user_id)
            for user_id in AITeammateProfile.objects.filter(workspace_id=workspace_id).values_list("user_id", flat=True)
        )

        run_rows: list[dict[str, Any]] = []
        runs = DeepRun.objects.filter(workspace_id=workspace_id, created_at__gte=window_start).only(
            "id", "status", "user_id"
        )
        for run in runs.iterator(chunk_size=500):
            run_rows.append({"id": str(run.id), "status": run.status, "user_id": str(run.user_id)})

        tool_rows: list[dict[str, Any]] = []
        logs = DeepRunLog.objects.filter(
            deep_run__workspace_id=workspace_id,
            event_type="tool_observation",
            created_at__gte=window_start,
        ).only("id", "agent_type", "tool_name")
        for log in logs.iterator(chunk_size=500):
            tool_rows.append({"agent_type": log.agent_type or "unknown", "tool_name": log.tool_name or "unknown"})

        return AiActivityRows(run_rows=run_rows, tool_rows=tool_rows, service_user_ids=service_user_ids)

    def collect_capability_agent_rows(self, *, workspace_id: str) -> list[dict[str, Any]]:
        from components.agents.application.services.ai_governance_service import _POWER_FLAG_KEYS
        from infrastructure.persistence.ai.agents.models import Agent

        agent_rows: list[dict[str, Any]] = []
        agents = Agent.objects.filter(workspace_id=str(workspace_id)).only("agent_id", "agent_type", "status", "config")
        for agent in agents.iterator(chunk_size=500):
            config = agent.config if isinstance(agent.config, dict) else {}
            capabilities = config.get("capabilities") if isinstance(config.get("capabilities"), dict) else {}
            power_flags = {key: bool(config.get(key)) for key in _POWER_FLAG_KEYS if key in config}
            agent_rows.append(
                {
                    "agent_id": str(agent.agent_id),
                    "agent_type": agent.agent_type,
                    "status": agent.status,
                    "capabilities": capabilities,
                    "power_flags": power_flags,
                    "grant_audit_entries": self._grant_audit_entries(agent),
                }
            )
        return agent_rows

    def collect_kill_switch_inventory(self, *, workspace_id: str) -> KillSwitchInventory:
        from infrastructure.persistence.ai.agents.models import Agent, DeepRun
        from infrastructure.persistence.ai.models import AITeammateProfile

        workspace_id = str(workspace_id)

        profile = AITeammateProfile.objects.filter(workspace_id=workspace_id).first()
        teammate_profile = (
            {"status": profile.status, "is_enabled": bool(profile.is_enabled)} if profile is not None else None
        )

        agent_rows = [
            {"agent_id": str(agent.agent_id), "agent_type": agent.agent_type, "status": agent.status}
            for agent in Agent.objects.filter(workspace_id=workspace_id)
            .only("agent_id", "agent_type", "status")
            .iterator(chunk_size=500)
        ]
        in_flight = DeepRun.objects.filter(
            workspace_id=workspace_id, status__in=(DeepRun.STATUS_PENDING, DeepRun.STATUS_RUNNING)
        ).count()

        return KillSwitchInventory(
            teammate_profile=teammate_profile,
            agent_rows=agent_rows,
            in_flight_deep_runs=in_flight,
        )

    @staticmethod
    def _grant_audit_entries(agent) -> list[dict[str, Any]]:
        """Read-only audit history for the agent's capability grants.

        Goes through the audit context's application provider (never its
        infrastructure directly). Best-effort: an audit read failure yields an
        empty history — reported as "not recorded", never invented."""
        try:
            from components.audit.application.providers.audit_log_provider import get_audit_log_provider

            entries = get_audit_log_provider().get_entity_history(
                instance=agent,
                field_name="capabilities",
                limit=_MAX_AUDIT_ENTRIES_PER_AGENT,
            )
        except Exception:
            logger.warning("capability grant audit read failed agent_id=%s", agent.agent_id, exc_info=True)
            return []
        rows = []
        for entry in entries:
            created_at = _parse_iso(getattr(entry, "created_at", None))
            rows.append(
                {
                    "field_name": getattr(entry, "field_name", ""),
                    "previous_value": getattr(entry, "previous_value", None),
                    "new_value": getattr(entry, "new_value", None),
                    "actor_id": getattr(entry, "actor_id", None),
                    "actor_display": getattr(entry, "actor_display", ""),
                    "reason": getattr(entry, "reason", ""),
                    "created_at": created_at.isoformat() if created_at else None,
                }
            )
        return rows
