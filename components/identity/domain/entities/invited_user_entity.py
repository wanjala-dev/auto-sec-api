"""Pure domain entity for an invited user."""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class InvitedUserEntity:
    """Immutable snapshot of a pending invitation."""

    id: int
    email: str
    invitation_code: UUID
    created_at: datetime.datetime
    updated_at: datetime.datetime
