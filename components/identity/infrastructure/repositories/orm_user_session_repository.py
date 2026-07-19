"""ORM adapter implementing SessionRegistryPort.

Backed by ``infrastructure.persistence.users.models.UserSession`` — one row
per issued refresh token (jti-stable because refresh rotation is OFF).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID

from components.identity.application.ports.geoip_port import GeoLocation
from components.identity.application.ports.session_registry_port import SessionRegistryPort
from components.identity.application.ports.user_agent_parser_port import DeviceInfo
from components.identity.domain.value_objects.auth_tokens import RequestContext
from components.identity.domain.value_objects.session_records import UserSessionRecord

logger = logging.getLogger(__name__)


def _aware_utc(value: datetime | None) -> datetime | None:
    """Normalize an ORM datetime to timezone-aware UTC.

    Runtime settings run USE_TZ=False (naive datetimes, TIME_ZONE="UTC")
    while test settings run USE_TZ=True (aware), so ORM datetimes arrive
    naive in production but aware under pytest. The domain compares against
    aware UTC, which made UserSessionRecord.is_active raise "can't compare
    offset-naive and offset-aware datetimes" on the live server while every
    test stayed green. The settings quirk is an infrastructure concern —
    normalize here so the domain only ever sees aware UTC.
    """
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def _to_record(session) -> UserSessionRecord:
    """ORM row → framework-free read model (datetimes normalized to aware UTC)."""
    return UserSessionRecord(
        id=session.id,
        user_id=session.user_id,
        refresh_jti=session.refresh_jti,
        login_method=session.login_method,
        ip_address=session.ip_address,
        user_agent=session.user_agent,
        device_type=session.device_type,
        browser=session.browser,
        browser_version=session.browser_version,
        os=session.os,
        os_version=session.os_version,
        geo_city=session.geo_city,
        geo_country=session.geo_country,
        geo_country_code=session.geo_country_code,
        enriched_at=_aware_utc(session.enriched_at),
        created_at=_aware_utc(session.created_at),
        last_seen_at=_aware_utc(session.last_seen_at),
        expires_at=_aware_utc(session.expires_at),
        revoked_at=_aware_utc(session.revoked_at),
        revoked_reason=session.revoked_reason,
    )


class OrmUserSessionRepository(SessionRegistryPort):
    """Concrete session registry backed by the Django ORM."""

    def create_session(
        self,
        *,
        user_id: UUID,
        refresh_jti: str,
        expires_at: datetime,
        context: RequestContext | None,
        login_method: str,
    ) -> None:
        # Session registration is observability, not authentication — a
        # registry failure MUST NOT break login, so this is the one place
        # a broad except is deliberate (log with traceback + continue).
        try:
            from django.utils import timezone

            from infrastructure.persistence.users.models import UserSession

            session, _created = UserSession.objects.update_or_create(
                refresh_jti=refresh_jti,
                defaults={
                    "user_id": user_id,
                    "login_method": login_method,
                    "ip_address": context.ip_address if context else None,
                    "user_agent": (context.user_agent if context else "") or "",
                    "expires_at": expires_at,
                    "last_seen_at": timezone.now(),
                },
            )
            self._after_create(session)
        except Exception:
            logger.exception(
                "user_session_create_failed user_id=%s jti=%s login_method=%s",
                user_id,
                refresh_jti,
                login_method,
            )

    def _after_create(self, session) -> None:
        """Dispatch async device/geo enrichment for a freshly-registered session.

        Fired AFTER the surrounding transaction commits so the worker can
        actually see the row, and guarded so a broker outage never breaks
        login (session enrichment is observability, not authentication).
        """
        from django.db import transaction

        session_id = str(session.id)

        def _dispatch() -> None:
            try:
                from components.identity.workers.tasks import enrich_user_session

                enrich_user_session.delay(session_id=session_id)
            except Exception:
                # Deliberate broad guard: Celery/broker downtime must never
                # surface to the login path. The daily sweep + re-login keep
                # enrichment eventually consistent.
                logger.exception("user_session_enrich_dispatch_failed session_id=%s", session_id)

        transaction.on_commit(_dispatch)

    def touch(self, *, refresh_jti: str, min_interval_seconds: int = 300) -> None:
        from django.utils import timezone

        from infrastructure.persistence.users.models import UserSession

        now = timezone.now()
        cutoff = now - timedelta(seconds=min_interval_seconds)
        UserSession.objects.filter(
            refresh_jti=refresh_jti,
            revoked_at__isnull=True,
            last_seen_at__lt=cutoff,
        ).update(last_seen_at=now)

    def revoke(self, *, refresh_jti: str, reason: str) -> None:
        from django.utils import timezone

        from infrastructure.persistence.users.models import UserSession

        UserSession.objects.filter(
            refresh_jti=refresh_jti,
            revoked_at__isnull=True,
        ).update(revoked_at=timezone.now(), revoked_reason=reason)

    def revoke_all_for_user(
        self,
        *,
        user_id: UUID,
        reason: str,
        except_jti: str | None = None,
    ) -> int:
        from django.utils import timezone

        from infrastructure.persistence.users.models import UserSession

        queryset = UserSession.objects.filter(user_id=user_id, revoked_at__isnull=True)
        if except_jti:
            queryset = queryset.exclude(refresh_jti=except_jti)
        return queryset.update(revoked_at=timezone.now(), revoked_reason=reason)

    def get(self, *, session_id: UUID) -> UserSessionRecord | None:
        from infrastructure.persistence.users.models import UserSession

        session = UserSession.objects.filter(id=session_id).first()
        return _to_record(session) if session else None

    def get_for_user(self, *, user_id: UUID, session_id: UUID) -> UserSessionRecord | None:
        from infrastructure.persistence.users.models import UserSession

        session = UserSession.objects.filter(id=session_id, user_id=user_id).first()
        return _to_record(session) if session else None

    def list_for_user(self, *, user_id: UUID, limit: int = 100) -> list[UserSessionRecord]:
        from infrastructure.persistence.users.models import UserSession

        sessions = UserSession.objects.filter(user_id=user_id).order_by("-last_seen_at")[:limit]
        return [_to_record(session) for session in sessions]

    def list_active_jtis_for_user(self, *, user_id: UUID, except_jti: str | None = None) -> list[str]:
        from django.utils import timezone

        from infrastructure.persistence.users.models import UserSession

        queryset = UserSession.objects.filter(
            user_id=user_id,
            revoked_at__isnull=True,
            expires_at__gt=timezone.now(),
        )
        if except_jti:
            queryset = queryset.exclude(refresh_jti=except_jti)
        return list(queryset.values_list("refresh_jti", flat=True))

    def apply_enrichment(
        self,
        *,
        session_id: UUID,
        device: DeviceInfo,
        geo: GeoLocation | None,
        enriched_at: datetime,
    ) -> bool:
        from infrastructure.persistence.users.models import UserSession

        updated = UserSession.objects.filter(id=session_id).update(
            device_type=device.device_type,
            browser=device.browser,
            browser_version=device.browser_version,
            os=device.os,
            os_version=device.os_version,
            geo_city=(geo.city if geo else "")[:128],
            geo_country=(geo.country if geo else "")[:64],
            geo_country_code=(geo.country_code if geo else "")[:2],
            enriched_at=enriched_at,
        )
        return bool(updated)
