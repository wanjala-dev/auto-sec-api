"""ORM adapter for agent graph dashboard query.

Phase 5 of the Agents-as-Teammates migration dropped action-related
fields from this query — AI findings live on the workspace's agent
team Kanban board now and are read via ``AIFindingsViewSet``. This
repo focuses on agent-level metadata only: enabled agent types,
currently running sessions, lifetime activity, and instance status.
"""
from __future__ import annotations

from typing import Any

from django.db.models import Count, Max, Q

from components.agents.application.ports.agent_graph_query_port import (
    AgentGraphData,
    AgentGraphQueryPort,
    AgentGraphRequest,
)


class OrmAgentGraphQueryRepository(AgentGraphQueryPort):

    def fetch_graph(self, *, request: AgentGraphRequest, http_request: Any) -> AgentGraphData:
        from infrastructure.persistence.ai.agents.models import Agent, AgentExecution
        from components.agents.infrastructure.services.agents_service import get_agent_service

        workspace_id = request.workspace_id

        # --- agent type nodes ---
        agent_service = get_agent_service()
        raw_types = agent_service.list_workspace_agent_types(workspace_id)
        agent_type_nodes = [
            {
                "id": entry["slug"],
                "label": entry["name"],
                "description": entry.get("description") or "",
                "summary": entry.get("summary") or "",
                "capabilities": entry.get("capabilities") or [],
                "examples": entry.get("examples") or [],
            }
            for entry in raw_types
            if entry.get("is_enabled")
        ]

        # --- sessions ---
        session_qs = AgentExecution.objects.filter(
            agent__workspace_id=workspace_id,
        ).select_related("agent")
        if not request.include_inactive:
            session_qs = session_qs.filter(
                status__in=[AgentExecution.STATUS_PENDING, AgentExecution.STATUS_RUNNING],
            )

        sessions = [
            {
                "id": str(ex.id),
                "agent_type": ex.agent.agent_type,
                "status": ex.status,
                "progress": ex.progress or 0,
                "progress_ratio": min(max((ex.progress or 0) / 100, 0), 1),
                "started_at": ex.created_at.isoformat(),
                "updated_at": ex.updated_at.isoformat(),
            }
            for ex in session_qs
        ]

        # --- agent instances & activity ---
        agent_qs = Agent.objects.filter(workspace_id=workspace_id)
        if request.agent_type_filter:
            agent_qs = agent_qs.filter(agent_type=request.agent_type_filter)

        active_agent_types = list(
            agent_qs.filter(status="active")
            .values_list("agent_type", flat=True)
            .distinct()
            .order_by("agent_type")
        )

        agent_instances = [
            {
                "id": str(a.agent_id),
                "agent_type": a.agent_type,
                "status": a.status,
                "last_executed": a.last_executed.isoformat() if a.last_executed else None,
                "execution_count": a.execution_count,
            }
            for a in agent_qs.order_by("agent_type", "-last_executed", "-created_at")
        ]

        agent_type_activity = [
            {
                "agent_type": row["agent_type"],
                "active": row["active"],
                "paused": row["paused"],
                "completed": row["completed"],
                "error": row["error"],
                "latest_executed": (
                    row["latest_executed"].isoformat() if row["latest_executed"] else None
                ),
            }
            for row in agent_qs.values("agent_type").annotate(
                active=Count("agent_id", filter=Q(status="active")),
                paused=Count("agent_id", filter=Q(status="paused")),
                completed=Count("agent_id", filter=Q(status="completed")),
                error=Count("agent_id", filter=Q(status="error")),
                latest_executed=Max("last_executed"),
            ).order_by("agent_type")
        ]

        return AgentGraphData(
            agent_types=agent_type_nodes,
            sessions=sessions,
            active_agent_types=active_agent_types,
            agent_type_activity=agent_type_activity,
            agent_instances=agent_instances,
        )
