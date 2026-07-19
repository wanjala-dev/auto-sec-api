"""Use cases: Teammate profile operations.

No Django imports — depends only on ports.
"""
from __future__ import annotations

from typing import Any

from components.agents.application.ports.teammate_profile_port import (
    GetTeammateProfileRequest,
    TeammateProfileData,
    TeammateProfilePort,
    UpdateTeammateProfileCommand,
    UpdateTeammateProfileResult,
)
from components.shared_kernel.application.handlers import CommandHandler


class GetTeammateProfileUseCase:
    def __init__(self, port: TeammateProfilePort) -> None:
        self._port = port

    def execute(self, *, request: GetTeammateProfileRequest) -> TeammateProfileData:
        return self._port.get_teammate_profile(request=request)


class UpdateTeammateProfileUseCase(CommandHandler[UpdateTeammateProfileCommand]):
    def __init__(self, port: TeammateProfilePort) -> None:
        self._port = port

    def handle(self, command: UpdateTeammateProfileCommand) -> Any:
        """CommandHandler implementation."""
        return self.execute(command=command)

    def execute(self, *, command: UpdateTeammateProfileCommand) -> UpdateTeammateProfileResult:
        return self._port.update_teammate_profile(command=command)
