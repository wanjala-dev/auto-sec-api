"""Unit tests: session-registry wiring in the auth use cases (T2-S1).

Pure port fakes, no DB, no framework. Enters through the use cases:

* login creates a session ONLY when tokens actually mint (not on the
  otp_required short-circuit);
* OTP verification creates a session at ITS minting point;
* logout revokes sessions (all devices vs exactly the submitted jti);
* password change touches NO sessions — mirroring the fact that it does
  not revoke tokens today (sessions must never claim a token is dead
  while it still works).
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from uuid import uuid4

import pytest

from components.identity.application.commands.change_password_command import ChangePasswordCommand
from components.identity.application.commands.login_command import LoginCommand, LoginResult
from components.identity.application.commands.otp_commands import VerifyOTPCommand, VerifyOTPResult
from components.identity.application.ports.otp_device_port import OTPDeviceInfo
from components.identity.application.ports.session_registry_port import SessionRegistryPort
from components.identity.application.use_cases.change_password_use_case import ChangePasswordUseCase
from components.identity.application.use_cases.login_use_case import LoginUseCase
from components.identity.application.use_cases.logout_use_case import LogoutCommand, LogoutUseCase
from components.identity.application.use_cases.verify_otp_use_case import VerifyOTPUseCase
from components.identity.domain.entities.user_entity import UserEntity
from components.identity.domain.value_objects.auth_tokens import AuthTokenPair, PreAuthToken, RequestContext

pytestmark = pytest.mark.unit

_NOW = datetime.datetime(2026, 7, 16, tzinfo=datetime.UTC)
_CONTEXT = RequestContext(ip_address="203.0.113.9", user_agent="pytest-agent")


def _user(**overrides) -> UserEntity:
    defaults = {}
    defaults.update(
        id=uuid4(),
        username="tester",
        email="tester@example.com",
        first_name="Test",
        last_name="Er",
        is_verified=True,
        is_active=True,
        is_staff=False,
        is_onboard_complete=True,
        is_contributor=False,
        two_factor_enabled=False,
        auth_provider="email",
        created_at=_NOW,
        updated_at=_NOW,
        two_factor_confirmed_at=None,
    )
    defaults.update(overrides)
    return UserEntity(**defaults)


# ── Fakes ────────────────────────────────────────────────────────────


@dataclass
class FakeSessionRegistry(SessionRegistryPort):
    created: list[dict] = field(default_factory=list)
    touched: list[str] = field(default_factory=list)
    revoked: list[tuple[str, str]] = field(default_factory=list)
    revoked_all: list[dict] = field(default_factory=list)

    def create_session(self, *, user_id, refresh_jti, expires_at, context, login_method):
        self.created.append(
            {
                "user_id": user_id,
                "refresh_jti": refresh_jti,
                "expires_at": expires_at,
                "context": context,
                "login_method": login_method,
            }
        )

    def touch(self, *, refresh_jti, min_interval_seconds=300):
        self.touched.append(refresh_jti)

    def revoke(self, *, refresh_jti, reason):
        self.revoked.append((refresh_jti, reason))

    def revoke_all_for_user(self, *, user_id, reason, except_jti=None):
        self.revoked_all.append({"user_id": user_id, "reason": reason, "except_jti": except_jti})
        return 1

    # Read/enrichment surface added in T2-S2/S3 — unused by these wiring tests.
    def get(self, *, session_id):
        return None

    def get_for_user(self, *, user_id, session_id):
        return None

    def list_for_user(self, *, user_id, limit=100):
        return []

    def list_active_jtis_for_user(self, *, user_id, except_jti=None):
        return []

    def apply_enrichment(self, *, session_id, device, geo, enriched_at):
        return False


class FakeAuthPort:
    def __init__(self, user: UserEntity | None):
        self._user = user

    def authenticate(self, email, password):
        return self._user

    def find_by_email(self, email):
        return self._user

    def get_auth_provider(self, email):
        return "email" if self._user else None


class FakeLockoutPort:
    def get_failure_count(self, scope, identifier):
        return 0

    def is_locked(self, scope, identifier):
        return (False, 0)

    def increment_failure(self, scope, identifier):
        return 1

    def activate_lockout(self, scope, identifier, window_minutes):
        pass

    def clear(self, scope, identifier):
        pass


@dataclass
class FakeAuditPort:
    events: list[dict] = field(default_factory=list)

    def record_event(self, *, event_code, user_id, email, success, context, metadata):
        self.events.append(
            {
                "event_code": event_code,
                "user_id": user_id,
                "success": success,
                "metadata": metadata,
            }
        )


class FakeTokenPort:
    def __init__(self, jti: str = "jti-abc123"):
        self.jti = jti

    def issue_tokens(self, user_id, *, otp_verified, device_id, include_refresh):
        return AuthTokenPair(
            access="access-token",
            refresh="refresh-token" if include_refresh else None,
            refresh_jti=self.jti if include_refresh else None,
            refresh_expires_at=(_NOW + datetime.timedelta(days=20)) if include_refresh else None,
        )

    def issue_preauth_token(self, user_id, lifetime_minutes):
        return PreAuthToken(access="preauth-token", requires_otp=True)

    def decode_token(self, token):
        return None


class FakeOTPPort:
    def __init__(self, totp_device: OTPDeviceInfo | None = None, verify_ok: bool = True):
        self._totp = totp_device
        self._verify_ok = verify_ok

    def get_totp_device(self, user_id, *, confirmed=None):
        return self._totp

    def get_static_device(self, user_id):
        return None

    def create_totp_device(self, user_id, *, name="default"):
        raise NotImplementedError

    def confirm_totp_device(self, device_id):
        pass

    def verify_token(self, device_id, token, *, method="totp"):
        return self._verify_ok

    def delete_device(self, device_id, *, method="totp"):
        pass

    def get_totp_config_url(self, device_id):
        return ""

    def create_or_get_totp_device(self, user_id):
        raise NotImplementedError

    def delete_all_devices(self, user_id):
        pass


class FakeNotificationPort:
    def notify_security_event(self, *, actor_id, user_id, verb, event_code, metadata):
        pass


@dataclass
class FakeTokenRevocation:
    revoked_all_for: list = field(default_factory=list)
    revoked_jtis: list[str] = field(default_factory=list)

    def revoke_all_tokens(self, *, user_id):
        self.revoked_all_for.append(user_id)
        return 2

    def revoke_token(self, *, token_string):
        return True

    def revoke_by_jti(self, *, jti):
        self.revoked_jtis.append(jti)
        return True


class FakeUserRepo:
    def check_password(self, user_id, password):
        return password == "old-password"

    def validate_new_password(self, user_id, password):
        return []

    def set_password(self, user_id, password):
        self.password_set = True

    def enable_two_factor(self, user_id):
        pass


# ── Login ────────────────────────────────────────────────────────────


def _login_use_case(user, sessions, token_port=None, otp_port=None, audit=None):
    return LoginUseCase(
        auth_port=FakeAuthPort(user),
        lockout_port=FakeLockoutPort(),
        audit_port=audit or FakeAuditPort(),
        token_port=token_port or FakeTokenPort(),
        otp_port=otp_port or FakeOTPPort(),
        notification_port=FakeNotificationPort(),
        session_registry=sessions,
    )


class TestLoginSessionCreation:
    def test_login_success_creates_session_with_password_method(self):
        user = _user()
        sessions = FakeSessionRegistry()
        audit = FakeAuditPort()
        result = _login_use_case(user, sessions, audit=audit).execute(
            LoginCommand(email=user.email, password="pw", context=_CONTEXT)
        )

        assert isinstance(result, LoginResult)
        assert len(sessions.created) == 1
        created = sessions.created[0]
        assert created["user_id"] == user.id
        assert created["refresh_jti"] == "jti-abc123"
        assert created["login_method"] == "password"
        assert created["context"] is _CONTEXT
        # Audit event carries the session jti for FK linkage.
        login_events = [e for e in audit.events if e["success"]]
        assert login_events and login_events[-1]["metadata"] == {"session_jti": "jti-abc123"}

    def test_login_otp_required_short_circuit_creates_no_session(self):
        user = _user(two_factor_enabled=True)
        sessions = FakeSessionRegistry()
        device = OTPDeviceInfo(device_id=1, name="totp", confirmed=True)
        result = _login_use_case(user, sessions, otp_port=FakeOTPPort(totp_device=device)).execute(
            LoginCommand(email=user.email, password="pw", context=_CONTEXT)
        )

        assert isinstance(result, LoginResult)
        assert result.otp_required is True
        assert sessions.created == []

    def test_login_failure_creates_no_session(self):
        sessions = FakeSessionRegistry()
        _login_use_case(None, sessions).execute(
            LoginCommand(email="nobody@example.com", password="bad", context=_CONTEXT)
        )
        assert sessions.created == []


# ── OTP verify ───────────────────────────────────────────────────────


class TestVerifyOtpSessionCreation:
    def test_otp_verify_success_creates_session_with_otp_method(self):
        user_id = uuid4()
        sessions = FakeSessionRegistry()
        audit = FakeAuditPort()
        device = OTPDeviceInfo(device_id=1, name="totp", confirmed=True)
        use_case = VerifyOTPUseCase(
            otp_port=FakeOTPPort(totp_device=device, verify_ok=True),
            lockout_port=FakeLockoutPort(),
            audit_port=audit,
            token_port=FakeTokenPort(jti="jti-otp-1"),
            user_repo=FakeUserRepo(),
            session_registry=sessions,
        )
        result = use_case.execute(
            VerifyOTPCommand(
                user_id=user_id,
                email="tester@example.com",
                token="123456",
                method="totp",
                context=_CONTEXT,
            )
        )

        assert isinstance(result, VerifyOTPResult)
        assert len(sessions.created) == 1
        assert sessions.created[0]["login_method"] == "otp"
        assert sessions.created[0]["refresh_jti"] == "jti-otp-1"
        success_events = [e for e in audit.events if e["success"]]
        assert success_events[-1]["metadata"]["session_jti"] == "jti-otp-1"

    def test_otp_verify_failure_creates_no_session(self):
        sessions = FakeSessionRegistry()
        device = OTPDeviceInfo(device_id=1, name="totp", confirmed=True)
        use_case = VerifyOTPUseCase(
            otp_port=FakeOTPPort(totp_device=device, verify_ok=False),
            lockout_port=FakeLockoutPort(),
            audit_port=FakeAuditPort(),
            token_port=FakeTokenPort(),
            user_repo=FakeUserRepo(),
            session_registry=sessions,
        )
        use_case.execute(
            VerifyOTPCommand(
                user_id=uuid4(),
                email="tester@example.com",
                token="000000",
                method="totp",
                context=_CONTEXT,
            )
        )
        assert sessions.created == []


# ── Logout ───────────────────────────────────────────────────────────


class TestLogoutSessionRevocation:
    def _use_case(self, sessions, revocation=None):
        return LogoutUseCase(
            token_revocation=revocation or FakeTokenRevocation(),
            audit_port=FakeAuditPort(),
            session_registry=sessions,
        )

    def test_logout_all_devices_revokes_all_sessions(self):
        user_id = uuid4()
        sessions = FakeSessionRegistry()
        revocation = FakeTokenRevocation()
        self._use_case(sessions, revocation).execute(
            LogoutCommand(
                user_id=user_id,
                email="tester@example.com",
                all_devices=True,
                context=_CONTEXT,
                refresh_jti="jti-current",
            )
        )
        assert revocation.revoked_all_for == [user_id]
        assert sessions.revoked_all == [{"user_id": user_id, "reason": "logout", "except_jti": None}]
        assert sessions.revoked == []

    def test_logout_single_device_revokes_only_that_session(self):
        sessions = FakeSessionRegistry()
        self._use_case(sessions).execute(
            LogoutCommand(
                user_id=uuid4(),
                email="tester@example.com",
                all_devices=False,
                context=_CONTEXT,
                refresh_jti="jti-current",
            )
        )
        assert sessions.revoked == [("jti-current", "logout")]
        assert sessions.revoked_all == []

    def test_logout_single_device_without_jti_touches_no_sessions(self):
        sessions = FakeSessionRegistry()
        self._use_case(sessions).execute(
            LogoutCommand(
                user_id=uuid4(),
                email="tester@example.com",
                all_devices=False,
                context=_CONTEXT,
            )
        )
        assert sessions.revoked == []
        assert sessions.revoked_all == []


# ── Password change ──────────────────────────────────────────────────


class TestChangePasswordSessionParity:
    def test_change_password_touches_no_sessions(self):
        """DELIBERATE (T2-S1): ChangePasswordUseCase does not revoke tokens
        today, so it must not revoke sessions either — the registry must
        never mark a session revoked while its refresh token still works.
        If token revocation is ever added to password change, session
        revocation (reason="password_change") must be added in the same
        change, and this test flipped."""
        use_case = ChangePasswordUseCase(
            user_repo=FakeUserRepo(),
            audit_port=FakeAuditPort(),
            notification_port=FakeNotificationPort(),
        )
        result = use_case.execute(
            ChangePasswordCommand(
                user_id=uuid4(),
                email="tester@example.com",
                old_password="old-password",
                new_password="brand-new-password-9",
                confirm_password="brand-new-password-9",
                context=_CONTEXT,
            )
        )
        # Success — and the use case has no session registry dependency at
        # all, which is the strongest form of "does not touch sessions".
        assert getattr(result, "success", False) is True
        assert not hasattr(use_case, "_sessions")
