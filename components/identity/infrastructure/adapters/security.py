"""Security-event helpers used by authentication flows.

CONSTRAINTS:
- Caller must provide request-derived metadata (IP, user agent).
- Events are idempotent per recipient and event_code.
- This module does not perform authentication or permission checks.
"""

from datetime import timedelta

from django.contrib.auth import get_user_model

from components.identity.infrastructure.adapters.cache_lockout_adapter import CacheLockoutAdapter
from components.notifications.infrastructure.adapters.notification_service import NotificationDispatcher
from infrastructure.persistence.notifications.models import Notification
from infrastructure.persistence.users.models import AuthAuditEvent


def record_security_event(*, actor_id, user_id, verb, event_code, metadata=None):
    """Persist a security event and dispatch notification side effects.

    CONSTRAINTS:
    - Will no-op if the user cannot be resolved.
    - Duplicate suppression is the dispatcher's dedup window (repeat events
      within the window reuse the existing Notification row).
    """

    if not user_id:
        return
    metadata = metadata or {}
    if event_code and "event" not in metadata:
        metadata["event"] = event_code

    User = get_user_model()
    user = User.objects.filter(id=user_id).first()
    if not user:
        return

    actor = User.objects.filter(id=actor_id).first() if actor_id else None
    if not actor:
        actor = user

    # allow_self_notify: security events are almost always self-actor (the
    # user changed their own password / logged in from a new device) — the
    # dispatcher must not drop them. The raw-create fallback that used to
    # live here existed only to work around that no-op; the funnel now
    # handles it, and dedup happens via create_notification's window.
    dispatcher = NotificationDispatcher()
    dispatcher.dispatch(
        actor=actor,
        workspace=None,
        verb=verb,
        notification_type=Notification.NotificationType.SYSTEM,
        recipients=[user],
        metadata=metadata,
        allow_self_notify=True,
    )


def _request_ip(request):
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return str(forwarded).split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def record_auth_audit_event(*, event_code, request, user=None, email="", success=True, metadata=None):
    """Persist auth/2FA events for forensics and support operations."""

    AuthAuditEvent.objects.create(
        user=user,
        email=(email or getattr(user, "email", "") or "").strip().lower(),
        event_code=event_code,
        success=bool(success),
        ip_address=_request_ip(request),
        user_agent=request.META.get("HTTP_USER_AGENT", "")[:1024],
        metadata=metadata or {},
    )


_LOCKOUT_WINDOW = timedelta(minutes=15)
_LOCKOUT_THRESHOLD = 5
_LOCKOUT_WARN_AT = 3

# Module singleton for lockout state management
_lockout = CacheLockoutAdapter()


def check_auth_lockout(*, scope: str, identifier: str):
    """Return lockout status for identifier within scope."""

    locked, remaining_seconds = _lockout.is_locked(scope=scope, identifier=identifier)
    return locked, remaining_seconds


def register_auth_failure(*, scope: str, identifier: str):
    """Track failure and activate lockout after threshold."""

    failure_count = _lockout.increment_failure(scope=scope, identifier=identifier)

    if failure_count >= _LOCKOUT_THRESHOLD:
        _lockout.activate_lockout(
            scope=scope,
            identifier=identifier,
            window_minutes=int(_LOCKOUT_WINDOW.total_seconds() / 60),
        )

    locked, remaining_seconds = check_auth_lockout(scope=scope, identifier=identifier)
    remaining_attempts = max(_LOCKOUT_THRESHOLD - failure_count, 0)

    return {
        "locked": locked,
        "remaining_seconds": remaining_seconds,
        "remaining_attempts": remaining_attempts,
        "warn": failure_count >= _LOCKOUT_WARN_AT and not locked,
    }


def clear_auth_failures(*, scope: str, identifier: str):
    _lockout.clear(scope=scope, identifier=identifier)
