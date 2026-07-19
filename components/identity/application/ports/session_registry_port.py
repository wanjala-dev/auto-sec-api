"""Port for the login-session registry.

One session row per issued refresh token (refresh-token rotation is OFF,
so a refresh jti is a stable session identifier for a login's lifetime).
The application layer registers, touches, and revokes sessions through
this port; infrastructure owns the ORM-backed implementation.

Session registration is observability, not authentication: a failure to
record a session MUST NEVER break login. Adapters implement
``create_session`` accordingly (log + continue).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from uuid import UUID

from components.identity.application.ports.geoip_port import GeoLocation
from components.identity.application.ports.user_agent_parser_port import DeviceInfo
from components.identity.domain.value_objects.auth_tokens import RequestContext
from components.identity.domain.value_objects.session_records import UserSessionRecord


class SessionRegistryPort(ABC):
    """Secondary/driven port for login-session bookkeeping."""

    @abstractmethod
    def create_session(
        self,
        *,
        user_id: UUID,
        refresh_jti: str,
        expires_at: datetime,
        context: RequestContext | None,
        login_method: str,
    ) -> None:
        """Register (idempotently, keyed on ``refresh_jti``) a new login session.

        MUST NOT raise — a session-registry failure never breaks login.
        """

    @abstractmethod
    def touch(self, *, refresh_jti: str, min_interval_seconds: int = 300) -> None:
        """Bump the session's ``last_seen_at``, throttled.

        Only updates when the current ``last_seen_at`` is older than
        ``min_interval_seconds``, so hot refresh loops don't write on
        every request. No-op for unknown or revoked sessions.
        """

    @abstractmethod
    def revoke(self, *, refresh_jti: str, reason: str) -> None:
        """Mark one session revoked (idempotent — already-revoked rows keep
        their original ``revoked_at``/``revoked_reason``)."""

    @abstractmethod
    def revoke_all_for_user(
        self,
        *,
        user_id: UUID,
        reason: str,
        except_jti: str | None = None,
    ) -> int:
        """Revoke every active session for ``user_id`` (optionally sparing
        ``except_jti``). Returns the number of sessions revoked."""

    @abstractmethod
    def get(self, *, session_id: UUID) -> UserSessionRecord | None:
        """Fetch one session by primary key, or ``None`` when unknown."""

    @abstractmethod
    def get_for_user(self, *, user_id: UUID, session_id: UUID) -> UserSessionRecord | None:
        """Fetch one session by primary key scoped to its owner.

        Returns ``None`` when the session does not exist OR belongs to a
        different user — callers translate that to a 404 without leaking
        the existence of other users' sessions.
        """

    @abstractmethod
    def list_for_user(self, *, user_id: UUID, limit: int = 100) -> list[UserSessionRecord]:
        """List the user's sessions ordered by ``-last_seen_at``, capped at
        ``limit`` rows. One query — no pagination."""

    @abstractmethod
    def list_active_jtis_for_user(self, *, user_id: UUID, except_jti: str | None = None) -> list[str]:
        """Refresh jtis of every active (not revoked, not expired) session
        for ``user_id``, optionally sparing ``except_jti``. Used to
        blacklist the matching refresh tokens when revoking sessions."""

    @abstractmethod
    def apply_enrichment(
        self,
        *,
        session_id: UUID,
        device: DeviceInfo,
        geo: GeoLocation | None,
        enriched_at: datetime,
    ) -> bool:
        """Persist parsed device/geo facts onto the session (idempotent —
        re-running overwrites). Returns ``False`` when the session row no
        longer exists."""
