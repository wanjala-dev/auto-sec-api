"""Serializers for the self-serve session + login-activity endpoints.

``MySessionSerializer`` renders the application-layer ``MySessionView``
projections (plain Serializer — no ORM access, the refresh jti never
reaches this layer). ``LoginActivityEventSerializer`` renders the user's
own ``AuthAuditEvent`` rows; its session summary reads only the
select_related ``session`` object, so the feeding queryset keeps the
page at a constant query count.
"""

from __future__ import annotations

from django.utils import timezone
from rest_framework import serializers

from infrastructure.persistence.users.models import AuthAuditEvent, UserSession


class MySessionSerializer(serializers.Serializer):
    """One login session, as shown to its owner."""

    id = serializers.UUIDField(read_only=True)
    device_type = serializers.CharField(read_only=True)
    browser = serializers.CharField(read_only=True)
    browser_version = serializers.CharField(read_only=True)
    os = serializers.CharField(read_only=True)
    os_version = serializers.CharField(read_only=True)
    geo_city = serializers.CharField(read_only=True)
    geo_country = serializers.CharField(read_only=True)
    ip_address = serializers.IPAddressField(read_only=True, allow_null=True)
    login_method = serializers.CharField(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)
    last_seen_at = serializers.DateTimeField(read_only=True)
    is_active = serializers.BooleanField(read_only=True)
    is_current = serializers.BooleanField(read_only=True)


class LoginActivityEventSerializer(serializers.ModelSerializer):
    """Self view of one auth audit event — full detail incl. IP + UA.

    ``session`` summarises the linked login session's parsed device facts
    (None when the event never resolved a session). Reads ONLY the
    eager-loaded FK — no per-row queries.
    """

    session = serializers.SerializerMethodField()

    class Meta:
        model = AuthAuditEvent
        fields = [
            "id",
            "event_code",
            "success",
            "ip_address",
            "user_agent",
            "created_at",
            "session",
        ]

    def get_session(self, obj) -> dict | None:
        session = obj.session
        if session is None:
            return None
        return {
            "id": str(session.id),
            "device_type": session.device_type,
            "browser": session.browser,
            "os": session.os,
            "geo_city": session.geo_city,
            "geo_country": session.geo_country,
        }


def _member_summary(user, fallback_email: str = "") -> dict | None:
    """Compact member block for the org-level views.

    ``user`` may be None (the audit FK is SET_NULL for deleted accounts)
    — fall back to the email snapshotted on the event so the row stays
    attributable. Reads ONLY fields on the eager-loaded user row.
    """
    if user is None:
        if not fallback_email:
            return None
        return {"id": None, "email": fallback_email, "display_name": fallback_email}
    return {
        "id": str(user.id),
        "email": user.email,
        "display_name": user.username or user.email,
    }


def _session_is_active(session, now) -> bool:
    return session.revoked_at is None and session.expires_at > now


class WorkspaceLoginActivityEventSerializer(serializers.ModelSerializer):
    """Org-admin view of one member auth audit event.

    FULL detail — including ``ip_address`` and the raw ``user_agent`` —
    is intentionally exposed to workspace admins (decided by Henry,
    2026-07). Reads only the eager-loaded ``user`` and ``session`` FKs,
    so the feeding queryset keeps the page at a constant query count.
    """

    member = serializers.SerializerMethodField()
    session = serializers.SerializerMethodField()

    class Meta:
        model = AuthAuditEvent
        fields = [
            "id",
            "member",
            "event_code",
            "success",
            "ip_address",
            "user_agent",
            "created_at",
            "session",
        ]

    def get_member(self, obj) -> dict | None:
        return _member_summary(obj.user, fallback_email=obj.email)

    def get_session(self, obj) -> dict | None:
        session = obj.session
        if session is None:
            return None
        return {
            "id": str(session.id),
            "device_type": session.device_type,
            "browser": session.browser,
            "os": session.os,
            "geo_city": session.geo_city,
            "geo_country": session.geo_country,
            "is_active": _session_is_active(session, timezone.now()),
        }


class WorkspaceSessionSerializer(serializers.ModelSerializer):
    """Org-admin view of one member login session (full detail per
    Henry's decision — IP included). Reads only the eager-loaded
    ``user`` FK."""

    member = serializers.SerializerMethodField()
    is_active = serializers.SerializerMethodField()

    class Meta:
        model = UserSession
        fields = [
            "id",
            "member",
            "device_type",
            "browser",
            "browser_version",
            "os",
            "os_version",
            "geo_city",
            "geo_country",
            "ip_address",
            "login_method",
            "created_at",
            "last_seen_at",
            "is_active",
        ]

    def get_member(self, obj) -> dict | None:
        return _member_summary(obj.user)

    def get_is_active(self, obj) -> bool:
        return _session_is_active(obj, timezone.now())


class OrgAuditLogSettingsSerializer(serializers.Serializer):
    """`{enabled: bool}` — the per-workspace org audit-log visibility toggle.

    Same shape for the GET response and the PATCH/PUT input.
    """

    enabled = serializers.BooleanField()
