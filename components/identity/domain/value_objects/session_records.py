"""Value objects for login-session reads.

Framework-free data carriers returned by the session registry port so the
application layer never touches the ORM row directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True)
class UserSessionRecord:
    """Read-model snapshot of one UserSession row."""

    id: UUID
    user_id: UUID
    refresh_jti: str
    login_method: str
    ip_address: str | None
    user_agent: str
    device_type: str
    browser: str
    browser_version: str
    os: str
    os_version: str
    geo_city: str
    geo_country: str
    geo_country_code: str
    enriched_at: datetime | None
    created_at: datetime
    last_seen_at: datetime
    expires_at: datetime
    revoked_at: datetime | None
    revoked_reason: str

    def is_active(self, now: datetime) -> bool:
        """Active = not revoked AND not past its refresh-token expiry."""
        return self.revoked_at is None and self.expires_at > now


@dataclass(frozen=True)
class MySessionView:
    """User-facing projection of a session (never exposes the jti)."""

    id: UUID
    device_type: str
    browser: str
    browser_version: str
    os: str
    os_version: str
    geo_city: str
    geo_country: str
    ip_address: str | None
    login_method: str
    created_at: datetime
    last_seen_at: datetime
    is_active: bool
    is_current: bool
