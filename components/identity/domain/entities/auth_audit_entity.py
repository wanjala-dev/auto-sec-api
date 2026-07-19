"""Pure domain entity for authentication audit events."""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class AuthAuditEventEntity:
    """Immutable snapshot of an auth/2FA audit event."""

    id: int
    user_id: UUID | None
    email: str
    event_code: str
    success: bool
    ip_address: str | None
    user_agent: str
    metadata: dict
    created_at: datetime.datetime

    @property
    def is_failure(self) -> bool:
        return not self.success

    @property
    def is_login_event(self) -> bool:
        return self.event_code.startswith("auth.login")

    @property
    def is_otp_event(self) -> bool:
        return "otp" in self.event_code
