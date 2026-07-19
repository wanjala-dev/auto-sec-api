"""ORM adapter implementing AuthAuditPort."""

from __future__ import annotations

from uuid import UUID

from components.identity.application.ports.auth_audit_port import AuthAuditPort
from components.identity.domain.value_objects.auth_tokens import RequestContext
from infrastructure.persistence.users.models import AuthAuditEvent


class OrmAuthAuditRepository(AuthAuditPort):
    """Concrete adapter backed by Django ORM for auth audit events."""

    def record_event(
        self,
        *,
        event_code: str,
        user_id: UUID | None,
        email: str,
        success: bool,
        context: RequestContext,
        metadata: dict | None,
    ) -> None:
        from infrastructure.persistence.users.models import CustomUser, UserSession

        user = None
        if user_id:
            user = CustomUser.objects.filter(id=user_id).first()

        # Link the audit event to its login session when the use case put
        # the session jti into the metadata (jti is a stable session key —
        # refresh rotation is off). Best-effort: an unknown jti (e.g. the
        # session registry write failed) just leaves the FK null.
        session = None
        session_jti = (metadata or {}).get("session_jti")
        if session_jti:
            session = UserSession.objects.filter(refresh_jti=session_jti).first()

        AuthAuditEvent.objects.create(
            user=user,
            session=session,
            email=(email or "").strip().lower(),
            event_code=event_code,
            success=bool(success),
            ip_address=context.ip_address,
            user_agent=context.user_agent[:1024],
            metadata=metadata or {},
        )
