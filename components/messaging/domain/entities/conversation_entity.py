"""Conversation aggregate root.

A Conversation is the central concept in the messaging domain.  It
represents a communication channel between two (or, in future, more)
participants.  Thread-management state (archived, starred, muted) is
per-participant, not global — so one person archiving a conversation
does not affect the other person's view.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from components.messaging.domain.errors import (
    CannotMessageSelfError,
    NotAParticipantError,
)
from components.messaging.domain.value_objects import ConversationType


@dataclass
class Participant:
    """Per-user state within a conversation."""

    user_id: UUID
    role: str = "member"
    is_archived: bool = False
    is_starred: bool = False
    is_muted: bool = False
    last_read_at: datetime | None = None
    joined_at: datetime | None = None


@dataclass
class Conversation:
    """Aggregate root for a messaging conversation."""

    id: UUID | None = None
    conversation_type: str = ConversationType.PRIVATE
    workspace_id: UUID | None = None
    participants: list[Participant] = field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None

    # ── Invariants ──────────────────────────────────────────────────

    def validate_new_private(self) -> None:
        """Enforce rules for a new private conversation."""
        if len(self.participants) != 2:
            raise ValueError("A private conversation requires exactly two participants.")
        ids = [p.user_id for p in self.participants]
        if ids[0] == ids[1]:
            raise CannotMessageSelfError("Cannot start a conversation with yourself.")

    def ensure_participant(self, user_id: UUID) -> Participant:
        """Return the participant record or raise if the user is not in this conversation."""
        for p in self.participants:
            if p.user_id == user_id:
                return p
        raise NotAParticipantError(
            f"User {user_id} is not a participant of conversation {self.id}."
        )

    def other_participant(self, user_id: UUID) -> Participant:
        """In a 1:1 conversation, return the other participant."""
        self.ensure_participant(user_id)
        for p in self.participants:
            if p.user_id != user_id:
                return p
        raise NotAParticipantError("No other participant found.")
