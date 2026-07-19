"""Use cases and queries for agent entitlement / listing.

No Django imports — depends only on ports.
"""
from __future__ import annotations

from typing import Any

from components.agents.application.ports.agent_entitlement_port import (
    AgentEntitlementPort,
    EntitlementResult,
    ListAgentsRequest,
    ListAgentsResult,
    ListAgentTypesRequest,
    ListAgentTypesResult,
    SetEntitlementCommand,
)
from components.shared_kernel.application.handlers import CommandHandler


class SetAgentEntitlementUseCase(CommandHandler[SetEntitlementCommand]):
    def __init__(self, port: AgentEntitlementPort) -> None:
        self._port = port

    def handle(self, command: SetEntitlementCommand) -> Any:
        """CommandHandler implementation."""
        return self.execute(command=command)

    def execute(self, *, command: SetEntitlementCommand) -> EntitlementResult:
        return self._port.set_entitlement(command=command)


class ListAgentsQuery:
    def __init__(self, port: AgentEntitlementPort) -> None:
        self._port = port

    def execute(self, *, request: ListAgentsRequest) -> ListAgentsResult:
        return self._port.list_agents(request=request)


class ListAgentTypesQuery:
    def __init__(self, port: AgentEntitlementPort) -> None:
        self._port = port

    def execute(self, *, request: ListAgentTypesRequest) -> ListAgentTypesResult:
        return self._port.list_agent_types(request=request)
