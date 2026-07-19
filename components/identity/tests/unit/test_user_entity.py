"""Unit tests for the UserEntity domain entity."""

from datetime import datetime, timezone
from uuid import uuid4

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


class TestFullName:
    def test_first_and_last(self):
        user = _make_user(first_name="Jane", last_name="Doe")
        assert user.full_name == "Jane Doe"

    def test_first_name_only(self):
        user = _make_user(first_name="Jane", last_name="")
        assert user.full_name == "Jane"

    def test_last_name_only(self):
        user = _make_user(first_name="", last_name="Doe")
        assert user.full_name == "Doe"

    def test_empty_names(self):
        user = _make_user(first_name="", last_name="")
        assert user.full_name == ""


class TestTwoFactor:
    def test_has_two_factor_when_enabled_and_confirmed(self):
        user = _make_user(
            two_factor_enabled=True,
            two_factor_confirmed_at=datetime(2025, 3, 1, tzinfo=timezone.utc),
        )
        assert user.has_two_factor is True

    def test_no_two_factor_when_enabled_but_not_confirmed(self):
        user = _make_user(two_factor_enabled=True, two_factor_confirmed_at=None)
        assert user.has_two_factor is False

    def test_no_two_factor_when_disabled(self):
        user = _make_user(two_factor_enabled=False, two_factor_confirmed_at=None)
        assert user.has_two_factor is False


class TestAuthProvider:
    def test_email_auth(self):
        user = _make_user(auth_provider="email")
        assert user.is_email_auth is True
        assert user.is_social_auth is False

    def test_social_auth(self):
        user = _make_user(auth_provider="google")
        assert user.is_email_auth is False
        assert user.is_social_auth is True


class TestImmutability:
    def test_frozen_dataclass(self):
        user = _make_user()
        try:
            user.email = "other@example.com"
            assert False, "Should have raised FrozenInstanceError"
        except AttributeError:
            pass
