"""Unit tests for identity domain enums and constants."""

from components.identity.domain.enums import (
    AuthEventCode,
    AuthProvider,
    LOCKOUT_THRESHOLD,
    LOCKOUT_WARN_AT,
    LOCKOUT_WINDOW_MINUTES,
)


class TestAuthProvider:
    def test_email_value(self):
        assert AuthProvider.EMAIL == "email"

    def test_google_value(self):
        assert AuthProvider.GOOGLE == "google"

    def test_is_string_enum(self):
        assert isinstance(AuthProvider.EMAIL, str)


class TestAuthEventCode:
    def test_login_codes_start_with_auth_login(self):
        assert AuthEventCode.LOGIN.value.startswith("auth.login")
        assert AuthEventCode.LOGIN_FAILED.value.startswith("auth.login")

    def test_otp_codes_contain_otp(self):
        assert "otp" in AuthEventCode.OTP_VERIFY.value
        assert "otp" in AuthEventCode.OTP_VERIFY_FAILED.value

    def test_all_codes_start_with_auth(self):
        for code in AuthEventCode:
            assert code.value.startswith("auth."), f"{code.name} should start with 'auth.'"


class TestLockoutConstants:
    def test_threshold_greater_than_warn(self):
        assert LOCKOUT_THRESHOLD > LOCKOUT_WARN_AT

    def test_warn_is_positive(self):
        assert LOCKOUT_WARN_AT > 0

    def test_window_is_positive(self):
        assert LOCKOUT_WINDOW_MINUTES > 0
