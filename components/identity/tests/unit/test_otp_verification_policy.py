"""Unit tests for the OTP verification domain policy."""

from datetime import datetime, timezone
from uuid import uuid4

from components.identity.domain.policies.otp_verification_policy import (
    otp_bypass_allowed,
    requires_otp,
)
from components.identity.domain.entities.user_entity import UserEntity


def _make_user(**overrides) -> UserEntity:
    defaults = dict(
        id=uuid4(),
        username="jdoe",
        email="jdoe@example.com",
        first_name="Jane",
        last_name="Doe",
        is_verified=True,
        is_active=True,
        is_staff=False,
        is_onboard_complete=True,
        is_contributor=False,
        two_factor_enabled=False,
        auth_provider="email",
        created_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2025, 6, 1, tzinfo=timezone.utc),
    )
    defaults.update(overrides)
    return UserEntity(**defaults)


class TestRequiresOtp:
    def test_user_with_2fa_requires_otp(self):
        user = _make_user(two_factor_enabled=True)
        assert requires_otp(user) is True

    def test_user_without_2fa_does_not_require_otp(self):
        user = _make_user(two_factor_enabled=False)
        assert requires_otp(user) is False


class TestOtpBypassAllowed:
    def test_bypass_allowed_when_2fa_disabled(self):
        user = _make_user(two_factor_enabled=False)
        assert otp_bypass_allowed(user) is True

    def test_bypass_not_allowed_when_2fa_enabled(self):
        user = _make_user(two_factor_enabled=True)
        assert otp_bypass_allowed(user) is False

    def test_requires_and_bypass_are_inverses(self):
        user_with = _make_user(two_factor_enabled=True)
        user_without = _make_user(two_factor_enabled=False)
        assert requires_otp(user_with) != otp_bypass_allowed(user_with)
        assert requires_otp(user_without) != otp_bypass_allowed(user_without)
