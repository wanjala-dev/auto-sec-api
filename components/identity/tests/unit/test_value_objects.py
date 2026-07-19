"""Unit tests for identity value objects."""

from components.identity.domain.value_objects.auth_tokens import (
    AuthTokenPair,
    PreAuthToken,
    RequestContext,
)


class TestAuthTokenPair:
    def test_access_and_refresh(self):
        pair = AuthTokenPair(access="abc123", refresh="xyz789")
        assert pair.access == "abc123"
        assert pair.refresh == "xyz789"

    def test_refresh_defaults_to_none(self):
        pair = AuthTokenPair(access="abc123")
        assert pair.refresh is None

    def test_immutable(self):
        pair = AuthTokenPair(access="abc123", refresh="xyz789")
        try:
            pair.access = "changed"
            assert False, "Should have raised FrozenInstanceError"
        except AttributeError:
            pass


class TestPreAuthToken:
    def test_defaults_to_requires_otp(self):
        token = PreAuthToken(access="pre-auth-token")
        assert token.requires_otp is True

    def test_can_set_requires_otp_false(self):
        token = PreAuthToken(access="pre-auth-token", requires_otp=False)
        assert token.requires_otp is False

    def test_immutable(self):
        token = PreAuthToken(access="pre-auth-token")
        try:
            token.access = "changed"
            assert False, "Should have raised FrozenInstanceError"
        except AttributeError:
            pass


class TestRequestContext:
    def test_full_context(self):
        ctx = RequestContext(ip_address="10.0.0.1", user_agent="TestBot/1.0")
        assert ctx.ip_address == "10.0.0.1"
        assert ctx.user_agent == "TestBot/1.0"

    def test_null_ip(self):
        ctx = RequestContext(ip_address=None, user_agent="TestBot/1.0")
        assert ctx.ip_address is None
