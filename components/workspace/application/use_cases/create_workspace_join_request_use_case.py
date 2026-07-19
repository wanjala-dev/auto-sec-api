"""Use case: create a workspace join request.

Private workspaces gate access behind owner/admin approval. This use
case validates the request, persists it via the port, and returns a
result the API can serialise.
"""

from __future__ import annotations

from dataclasses import dataclass

from components.workspace.application.ports.workspace_join_request_port import (
    CreateJoinRequestCommand,
    JoinRequestResult,
    WorkspaceJoinRequestPort,
)


@dataclass
class CreateWorkspaceJoinRequestUseCase:
    store: WorkspaceJoinRequestPort

    def execute(self, command: CreateJoinRequestCommand) -> JoinRequestResult:
        return self.store.create_request(command=command)
