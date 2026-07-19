"""Domain entity for a workspace join request.

A user requests access to a private workspace; the workspace owner or
an admin reviews and approves or denies it. Approval creates a
``WorkspaceMembership``. The entity is immutable — state transitions
return new instances (plus an emitted event).
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field, replace
from uuid import UUID


class JoinRequestStatus:
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    WITHDRAWN = "withdrawn"

    _ALL = {PENDING, APPROVED, DENIED, WITHDRAWN}
    _TERMINAL = {APPROVED, DENIED, WITHDRAWN}

    @classmethod
    def validate(cls, value: str) -> str:
        if value not in cls._ALL:
            raise ValueError(f"Invalid join request status: {value}")
        return value

    @classmethod
    def is_terminal(cls, value: str) -> bool:
        return value in cls._TERMINAL


MAX_MESSAGE_LENGTH = 1000
MAX_REVIEW_NOTE_LENGTH = 500


@dataclass(frozen=True)
class WorkspaceJoinRequestEntity:
    id: UUID
    workspace_id: UUID
    requester_id: UUID
    message: str
    status: str
    requested_at: datetime.datetime
    reviewed_at: datetime.datetime | None = None
    reviewed_by_id: UUID | None = None
    review_note: str = ""

    def __post_init__(self) -> None:
        JoinRequestStatus.validate(self.status)
        if self.message and len(self.message) > MAX_MESSAGE_LENGTH:
            raise ValueError(
                f"Join request message exceeds {MAX_MESSAGE_LENGTH} characters."
            )
        if self.review_note and len(self.review_note) > MAX_REVIEW_NOTE_LENGTH:
            raise ValueError(
                f"Join request review note exceeds {MAX_REVIEW_NOTE_LENGTH} "
                f"characters."
            )
        if JoinRequestStatus.is_terminal(self.status):
            if self.status in (JoinRequestStatus.APPROVED, JoinRequestStatus.DENIED):
                if self.reviewed_at is None or self.reviewed_by_id is None:
                    raise ValueError(
                        "Approved/denied requests must carry reviewer metadata."
                    )

    @property
    def is_pending(self) -> bool:
        return self.status == JoinRequestStatus.PENDING

    @property
    def is_terminal(self) -> bool:
        return JoinRequestStatus.is_terminal(self.status)

    def approve(
        self,
        *,
        reviewer_id: UUID,
        reviewed_at: datetime.datetime,
        note: str = "",
    ) -> "WorkspaceJoinRequestEntity":
        if not self.is_pending:
            raise ValueError(
                f"Cannot approve a join request in status '{self.status}'."
            )
        return replace(
            self,
            status=JoinRequestStatus.APPROVED,
            reviewed_by_id=reviewer_id,
            reviewed_at=reviewed_at,
            review_note=note or "",
        )

    def deny(
        self,
        *,
        reviewer_id: UUID,
        reviewed_at: datetime.datetime,
        note: str = "",
    ) -> "WorkspaceJoinRequestEntity":
        if not self.is_pending:
            raise ValueError(
                f"Cannot deny a join request in status '{self.status}'."
            )
        return replace(
            self,
            status=JoinRequestStatus.DENIED,
            reviewed_by_id=reviewer_id,
            reviewed_at=reviewed_at,
            review_note=note or "",
        )

    def withdraw(self, *, at: datetime.datetime) -> "WorkspaceJoinRequestEntity":
        if not self.is_pending:
            raise ValueError(
                f"Cannot withdraw a join request in status '{self.status}'."
            )
        return replace(
            self,
            status=JoinRequestStatus.WITHDRAWN,
            reviewed_at=at,
        )
