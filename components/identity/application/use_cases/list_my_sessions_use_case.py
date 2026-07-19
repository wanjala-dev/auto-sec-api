"""Use case: list the authenticated user's login sessions.

Framework-free. Returns user-facing ``MySessionView`` projections — the
refresh jti never leaves the application layer. ``is_current`` compares
each session's jti with the ``sid`` claim of the access token that made
the request (None-safe: pre-sid tokens simply mark no session current).
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from components.identity.application.ports.session_registry_port import SessionRegistryPort
from components.identity.domain.value_objects.session_records import MySessionView

MAX_SESSIONS = 100


class ListMySessionsUseCase:
    """List sessions ordered by ``-last_seen_at``, capped at 100 rows."""

    def __init__(self, *, session_registry: SessionRegistryPort) -> None:
        self._sessions = session_registry

    def execute(self, *, user_id: UUID, current_sid: str | None) -> list[MySessionView]:
        now = datetime.now(UTC)
        records = self._sessions.list_for_user(user_id=user_id, limit=MAX_SESSIONS)
        return [
            MySessionView(
                id=record.id,
                device_type=record.device_type,
                browser=record.browser,
                browser_version=record.browser_version,
                os=record.os,
                os_version=record.os_version,
                geo_city=record.geo_city,
                geo_country=record.geo_country,
                ip_address=record.ip_address,
                login_method=record.login_method,
                created_at=record.created_at,
                last_seen_at=record.last_seen_at,
                is_active=record.is_active(now),
                is_current=bool(current_sid) and record.refresh_jti == current_sid,
            )
            for record in records
        ]
