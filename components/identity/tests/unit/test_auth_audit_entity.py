"""Unit tests for the AuthAuditEventEntity domain entity."""

from datetime import datetime, timezone
from uuid import uuid4

from components.identity.domain.entities.auth_audit_entity import AuthAuditEventEntity


def _make_audit_event(**overrides) -> AuthAuditEventEntity:
    defaults = dict(
        id=1,
        user_id=uuid4(),
        email="jdoe@example.com",
        event_code="auth.login",
        success=True,
        ip_address="192.168.1.1",
        user_agent="Mozilla/5.0",
        metadata={},
        created_at=datetime(2025, 6, 1, tzinfo=timezone.utc),
    )
    defaults.update(overrides)
    return AuthAuditEventEntity(**defaults)


class TestIsFailure:
    def test_success_is_not_failure(self):
        event = _make_audit_event(success=True)
        assert event.is_failure is False

    def test_failure_is_failure(self):
        event = _make_audit_event(success=False)
        assert event.is_failure is True


class TestIsLoginEvent:
    def test_login_event(self):
        event = _make_audit_event(event_code="auth.login")
        assert event.is_login_event is True

    def test_login_failed_event(self):
        event = _make_audit_event(event_code="auth.login_failed")
        assert event.is_login_event is True

    def test_otp_event_is_not_login(self):
        event = _make_audit_event(event_code="auth.otp_verify")
        assert event.is_login_event is False

    def test_password_reset_is_not_login(self):
        event = _make_audit_event(event_code="auth.password_reset_requested")
        assert event.is_login_event is False


class TestIsOtpEvent:
    def test_otp_verify_event(self):
        event = _make_audit_event(event_code="auth.otp_verify")
        assert event.is_otp_event is True

    def test_otp_verify_failed_event(self):
        event = _make_audit_event(event_code="auth.otp_verify_failed")
        assert event.is_otp_event is True

    def test_login_is_not_otp(self):
        event = _make_audit_event(event_code="auth.login")
        assert event.is_otp_event is False


class TestNullableFields:
    def test_null_user_id(self):
        event = _make_audit_event(user_id=None)
        assert event.user_id is None

    def test_null_ip_address(self):
        event = _make_audit_event(ip_address=None)
        assert event.ip_address is None
