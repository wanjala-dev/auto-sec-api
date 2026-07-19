"""Pure domain entity for a user in the Identity bounded context.

No ORM, no Django, no framework imports. This is the domain's view of a user.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from uuid import UUID


@dataclass(frozen=True)
class UserEntity:
    """Immutable snapshot of a user's identity state."""

    id: UUID
    username: str
    email: str
    first_name: str
    last_name: str
    is_verified: bool
    is_active: bool
    is_staff: bool
    is_onboard_complete: bool
    is_contributor: bool
    two_factor_enabled: bool
    auth_provider: str
    created_at: datetime.datetime
    updated_at: datetime.datetime
    two_factor_confirmed_at: datetime.datetime | None = None

    @property
    def full_name(self) -> str:
        parts = [self.first_name, self.last_name]
        return " ".join(p for p in parts if p).strip()

    @property
    def has_two_factor(self) -> bool:
        return self.two_factor_enabled and self.two_factor_confirmed_at is not None

    @property
    def is_email_auth(self) -> bool:
        return self.auth_provider == "email"

    @property
    def is_social_auth(self) -> bool:
        return self.auth_provider != "email"
