"""ORM adapter for agent entitlement and listing operations.

Extracted from agents_controller.py set_agent_entitlement, list_agents,
list_agent_types.
"""
from __future__ import annotations

from typing import Any

from components.agents.domain.errors import (
    AgentEngagementError,
    AgentNotFoundError,
    AgentPermissionError,
)
from components.agents.application.ports.agent_entitlement_port import (
    AgentEntitlementPort,
    EntitlementResult,
    ListAgentsRequest,
    ListAgentsResult,
    ListAgentTypesRequest,
    ListAgentTypesResult,
    SetEntitlementCommand,
)


def _parse_bool(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


class OrmAgentEntitlementRepository(AgentEntitlementPort):

    def set_entitlement(self, *, command: SetEntitlementCommand) -> EntitlementResult:
        from components.agents.application.policies.agent_entitlements import ensure_workspace_agent_type, resolve_agent_type
        from infrastructure.persistence.workspaces.models import Workspace

        if not command.workspace_id or not command.agent_type_slug:
            raise AgentEngagementError("workspace_id and agent_type are required")

        workspace = Workspace.objects.filter(id=command.workspace_id).first()
        if not workspace:
            raise AgentNotFoundError("Workspace not found")

        user = command.user
        if not (
            getattr(user, "is_staff", False)
            or str(workspace.workspace_owner_id) == str(getattr(user, "id", None))
        ):
            raise AgentPermissionError("Only the organization owner can manage agents.")

        agent_type = resolve_agent_type(str(command.agent_type_slug))
        if not agent_type:
            raise AgentEngagementError(f"Unknown agent type '{command.agent_type_slug}'")

        if agent_type.slug == "ai_teammate":
            raise AgentEngagementError("Use the AI enable toggle to manage the Orchestrator agent.")

        if command.is_enabled is None:
            raise AgentEngagementError("is_enabled is required")

        enabled_flag = (
            bool(command.is_enabled)
            if isinstance(command.is_enabled, bool)
            else _parse_bool(command.is_enabled)
        )

        if enabled_flag and not workspace.ai_teammate_enabled:
            raise AgentEngagementError("Enable AI for this organization before enabling agents.")

        entitlement = ensure_workspace_agent_type(
            str(workspace.id),
            agent_type,
            is_enabled=enabled_flag,
            updated_by=user,
        )

        return EntitlementResult(
            workspace_id=str(workspace.id),
            agent_type=agent_type.slug,
            is_enabled=entitlement.is_enabled,
            entitlement_id=str(entitlement.id),
        )

    def list_agents(self, *, request: ListAgentsRequest) -> ListAgentsResult:
        from components.agents.infrastructure.services.agents_service import get_agent_service

        factory = get_agent_service()
        user_agents = factory.list_user_agents(request.user_id)
        return ListAgentsResult(agents=user_agents, total=len(user_agents))

    def list_agent_types(self, *, request: ListAgentTypesRequest) -> ListAgentTypesResult:
        from components.agents.infrastructure.services.agents_service import get_agent_service
        from infrastructure.persistence.workspaces.models import Workspace

        service = get_agent_service()

        if request.workspace_id:
            workspace = Workspace.objects.filter(id=request.workspace_id).first()
            if not workspace:
                raise AgentNotFoundError("Workspace not found")
            # Permission check
            user = request.user
            if user and not (
                getattr(user, "is_staff", False)
                or str(workspace.workspace_owner_id) == str(getattr(user, "id", None))
                or workspace.workspace_teams.filter(members=user, status="active").exists()
                or workspace.followers.filter(id=getattr(user, "id", None)).exists()
            ):
                raise AgentPermissionError("Not authorized to view agent entitlements")

            catalogue = service.list_workspace_agent_types(
                request.workspace_id, include_inactive=request.include_inactive,
            )
            if request.enabled_only:
                catalogue = [entry for entry in catalogue if entry.get("is_enabled")]
        else:
            catalogue = service.list_available_agent_types(include_inactive=request.include_inactive)

        return ListAgentTypesResult(agent_types=catalogue, total=len(catalogue))
