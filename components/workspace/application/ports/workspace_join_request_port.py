"""Port: workspace join request operations.

Defines the interface the application layer uses to persist and load
join requests. Implemented by an ORM adapter in infrastructure.

No Django imports — standard library only.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Iterable


@dataclass(frozen=True)
class CreateJoinRequestCommand:
    workspace_id: str
    requester_id: str
    message: str = ""
    # Which team experience the requester asked for: "contributor" or
    # "volunteer". Approval copies this onto the membership persona.
    requested_persona: str = "contributor"


@dataclass(frozen=True)
class ReviewJoinRequestCommand:
    request_id: str
    reviewer_id: str
    reviewer_is_staff: bool = False
    reviewer_is_superuser: bool = False
    note: str = ""


@dataclass(frozen=True)
class WithdrawJoinRequestCommand:
    request_id: str
    actor_id: str


@dataclass
class JoinRequestResult:
    """Shape returned by create/approve/deny/withdraw use cases.

    Carries enough to surface in the API without a second query.
    """

    request_id: str = ""
    workspace_id: str = ""
    workspace_name: str = ""
    requester_id: str = ""
    requester_name: str = ""
    requester_email: str = ""
    status: str = ""
    message: str = ""
    requested_at: str = ""
    reviewed_at: str | None = None
    reviewed_by_id: str | None = None
    reviewed_by_name: str | None = None
    review_note: str = ""
    # On approve we also return the new membership id so callers can
    # navigate straight into the workspace.
    membership_id: str | None = None


@dataclass
class JoinRequestListResult:
    items: list[JoinRequestResult] = field(default_factory=list)
    total: int = 0


class WorkspaceJoinRequestPort(abc.ABC):
    """Secondary port for join request persistence + membership creation.

    Methods raise domain errors (``JoinRequestValidationError``,
    ``JoinRequestAlreadyExistsError``, ``JoinRequestPermissionError``,
    ``JoinRequestNotFoundError``) on policy violations.
    """

    @abc.abstractmethod
    def create_request(
        self, *, command: CreateJoinRequestCommand
    ) -> JoinRequestResult:
        ...

    @abc.abstractmethod
    def approve_request(
        self, *, command: ReviewJoinRequestCommand
    ) -> JoinRequestResult:
        ...

    @abc.abstractmethod
    def deny_request(
        self, *, command: ReviewJoinRequestCommand
    ) -> JoinRequestResult:
        ...

    @abc.abstractmethod
    def withdraw_request(
        self, *, command: WithdrawJoinRequestCommand
    ) -> JoinRequestResult:
        ...

    @abc.abstractmethod
    def list_pending_for_workspace(
        self,
        *,
        workspace_id: str,
        actor_id: str,
        actor_is_staff: bool = False,
        actor_is_superuser: bool = False,
    ) -> JoinRequestListResult:
        ...

    @abc.abstractmethod
    def list_mine(self, *, requester_id: str) -> JoinRequestListResult:
        ...
