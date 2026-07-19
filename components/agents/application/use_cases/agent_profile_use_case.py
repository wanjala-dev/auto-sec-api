"""Use cases and queries for agent profile / state.

No Django imports — depends only on ports.
"""

from __future__ import annotations

from typing import Any

from components.agents.application.ports.agent_profile_port import (
    AgentProfileData,
    AgentProfilePort,
    AgentStateData,
    GetAgentProfileRequest,
    GetAgentStateRequest,
    PatchAgentProfileCommand,
    PatchAgentProfileResult,
    PatchAgentSettingsCommand,
    PatchAgentSettingsResult,
)
from components.shared_kernel.application.handlers import CommandHandler


class GetAgentStateQuery:
    def __init__(self, port: AgentProfilePort) -> None:
        self._port = port

    def execute(self, *, request: GetAgentStateRequest) -> AgentStateData:
        return self._port.get_agent_state(request=request)


class GetAgentProfileQuery:
    def __init__(self, port: AgentProfilePort) -> None:
        self._port = port

    def execute(self, *, request: GetAgentProfileRequest) -> AgentProfileData:
        return self._port.get_agent_profile(request=request)


class PatchAgentProfileUseCase(CommandHandler[PatchAgentProfileCommand]):
    def __init__(self, port: AgentProfilePort) -> None:
        self._port = port

    def handle(self, command: PatchAgentProfileCommand) -> Any:
        """CommandHandler implementation."""
        return self.execute(command=command)

    def execute(self, *, command: PatchAgentProfileCommand) -> PatchAgentProfileResult:
        return self._port.patch_agent_profile(command=command)


class PatchAgentSettingsUseCase(CommandHandler[PatchAgentSettingsCommand]):
    def __init__(self, port: AgentProfilePort) -> None:
        self._port = port

    def handle(self, command: PatchAgentSettingsCommand) -> Any:
        """CommandHandler implementation."""
        return self.execute(command=command)

    def execute(self, *, command: PatchAgentSettingsCommand) -> PatchAgentSettingsResult:
        return self._port.patch_agent_settings(command=command)


class PatchAgentCapabilitiesUseCase:
    """Toggle allowlisted, risk-gating capabilities (e.g. ``open_draft_pr``)."""

    def __init__(self, port: AgentProfilePort) -> None:
        self._port = port

    def execute(self, *, command):
        return self._port.patch_agent_capabilities(command=command)
