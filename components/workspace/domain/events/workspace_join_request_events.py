"""Domain events for workspace join requests.

Emitted by the application use cases after a successful state transition.
Consumed by notification handlers (owner/requester emails + in-app).
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class WorkspaceJoinRequestCreated:
    request_id: UUID
    workspace_id: UUID
    requester_id: UUID
    message: str
    requested_at: datetime.datetime


@dataclass(frozen=True)
class WorkspaceJoinRequestApproved:
    request_id: UUID
    workspace_id: UUID
    requester_id: UUID
    reviewer_id: UUID
    approved_at: datetime.datetime
    note: str = ""


@dataclass(frozen=True)
class WorkspaceJoinRequestDenied:
    request_id: UUID
    workspace_id: UUID
    requester_id: UUID
    reviewer_id: UUID
    denied_at: datetime.datetime
    note: str = ""


@dataclass(frozen=True)
class WorkspaceJoinRequestWithdrawn:
    request_id: UUID
    workspace_id: UUID
    requester_id: UUID
    withdrawn_at: datetime.datetime
