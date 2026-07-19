"""Use cases for reviewing workspace join requests.

Approve promotes the requester to a ``WorkspaceMembership``; deny marks
the request rejected with an optional note; withdraw lets the requester
cancel a still-pending request before review.
"""

from __future__ import annotations

from dataclasses import dataclass

from components.workspace.application.ports.workspace_join_request_port import (
    JoinRequestResult,
    ReviewJoinRequestCommand,
    WithdrawJoinRequestCommand,
    WorkspaceJoinRequestPort,
)


@dataclass
class ApproveWorkspaceJoinRequestUseCase:
    store: WorkspaceJoinRequestPort

    def execute(self, command: ReviewJoinRequestCommand) -> JoinRequestResult:
        return self.store.approve_request(command=command)


@dataclass
class DenyWorkspaceJoinRequestUseCase:
    store: WorkspaceJoinRequestPort

    def execute(self, command: ReviewJoinRequestCommand) -> JoinRequestResult:
        return self.store.deny_request(command=command)


@dataclass
class WithdrawWorkspaceJoinRequestUseCase:
    store: WorkspaceJoinRequestPort

    def execute(self, command: WithdrawJoinRequestCommand) -> JoinRequestResult:
        return self.store.withdraw_request(command=command)
