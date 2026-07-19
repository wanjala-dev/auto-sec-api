"""Use case: Record an authentication audit event.

No Django imports — depends only on ports and value objects.
"""

from __future__ import annotations

from uuid import UUID

from components.identity.domain.value_objects.auth_tokens import RequestContext
from components.identity.application.ports.auth_audit_port import AuthAuditPort


class RecordAuditEventUseCase:
    """Application use case for recording auth/2FA audit events."""

    def __init__(self, audit_port: AuthAuditPort) -> None:
        self._audit_port = audit_port

    def execute(
        self,
        *,
        event_code: str,
        user_id: UUID | None,
        email: str,
        success: bool,
        context: RequestContext,
        metadata: dict | None = None,
    ) -> None:
        self._audit_port.record_event(
            event_code=event_code,
            user_id=user_id,
            email=email,
            success=success,
            context=context,
            metadata=metadata,
        )
