"""Integration tests: UserSession registry core (T2-S1).

Full-stack through the HTTP endpoints:

* login creates a UserSession row whose refresh_jti matches the returned
  refresh token's jti, with a ``sid`` claim on BOTH tokens;
* X-Forwarded-For parsing stores the FIRST hop only;
* token refresh bumps last_seen_at (throttled — an immediate second
  refresh does not write);
* revoke_by_jti blacklists exactly the targeted outstanding token;
* logout revokes the session row.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken

from components.identity.infrastructure.adapters.jwt_token_revocation_adapter import JWTTokenRevocationAdapter
from infrastructure.persistence.users.models import CustomUser, UserSession

pytestmark = pytest.mark.django_db

PASSWORD = "session-test-pass-123"


@pytest.fixture(autouse=True)
def disable_security_events_async(settings):
    settings.SECURITY_EVENTS_ASYNC = False


def _make_user(email: str = "session-tester@example.com") -> CustomUser:
    user = CustomUser.objects.create_user(
        email=email,
        username=email.split("@")[0],
        password=PASSWORD,
    )
    user.is_verified = True
    user.save(update_fields=["is_verified"])
    return user


def _login(api_client, user, **extra):
    return api_client.post(
        reverse("login"),
        {"email": user.email, "password": PASSWORD},
        format="json",
        **extra,
    )


class TestLoginCreatesSession:
    def test_session_row_matches_refresh_jti_and_sid_claims(self, api_client):
        user = _make_user()
        response = _login(api_client, user)
        assert response.status_code == 200

        tokens = response.data["tokens"]
        refresh = RefreshToken(tokens["refresh"])
        access = AccessToken(tokens["access"])
        refresh_jti = str(refresh["jti"])

        # sid claim present on BOTH tokens and equal to the refresh jti.
        assert str(refresh["sid"]) == refresh_jti
        assert str(access["sid"]) == refresh_jti

        session = UserSession.objects.get(refresh_jti=refresh_jti)
        assert session.user_id == user.id
        assert session.login_method == "password"
        assert session.revoked_at is None
        assert session.expires_at is not None
        assert session.last_seen_at is not None

        # The login audit event carries the jti in metadata AND links the
        # session FK (resolved inside OrmAuthAuditRepository).
        from infrastructure.persistence.users.models import AuthAuditEvent

        login_event = AuthAuditEvent.objects.filter(user=user, event_code="auth.login", success=True).latest(
            "created_at"
        )
        assert login_event.metadata.get("session_jti") == refresh_jti
        assert login_event.session_id == session.id

    def test_xff_first_hop_is_stored_as_session_ip(self, api_client):
        user = _make_user("xff-tester@example.com")
        response = _login(
            api_client,
            user,
            HTTP_X_FORWARDED_FOR="198.51.100.7, 203.0.113.1, 10.0.0.2",
            HTTP_USER_AGENT="pytest-browser/1.0",
        )
        assert response.status_code == 200
        refresh_jti = str(RefreshToken(response.data["tokens"]["refresh"])["jti"])
        session = UserSession.objects.get(refresh_jti=refresh_jti)
        assert session.ip_address == "198.51.100.7"
        assert session.user_agent == "pytest-browser/1.0"


class TestRefreshTouchesSession:
    def test_refresh_bumps_stale_last_seen_and_throttles_immediate_repeat(self, api_client):
        user = _make_user("refresh-tester@example.com")
        login_response = _login(api_client, user)
        refresh_token = login_response.data["tokens"]["refresh"]
        refresh_jti = str(RefreshToken(refresh_token)["jti"])

        # Age the session past the touch throttle window.
        stale = timezone.now() - timedelta(minutes=30)
        UserSession.objects.filter(refresh_jti=refresh_jti).update(last_seen_at=stale)

        response = api_client.post(reverse("token_refresh"), {"refresh": refresh_token}, format="json")
        assert response.status_code == 200
        assert "access" in response.data

        session = UserSession.objects.get(refresh_jti=refresh_jti)
        first_touch = session.last_seen_at
        assert first_touch > stale

        # Immediate second refresh: inside the 300s throttle → no write.
        response = api_client.post(reverse("token_refresh"), {"refresh": refresh_token}, format="json")
        assert response.status_code == 200
        session.refresh_from_db()
        assert session.last_seen_at == first_touch

    def test_refresh_with_garbage_token_still_returns_401_without_error(self, api_client):
        response = api_client.post(reverse("token_refresh"), {"refresh": "not-a-jwt"}, format="json")
        assert response.status_code == 401


class TestRevokeByJti:
    def test_blacklists_exactly_that_outstanding_token(self):
        user = _make_user("revoke-tester@example.com")
        keep = RefreshToken.for_user(user)
        kill = RefreshToken.for_user(user)
        kill_jti = str(kill["jti"])
        keep_jti = str(keep["jti"])

        adapter = JWTTokenRevocationAdapter()
        assert adapter.revoke_by_jti(jti=kill_jti) is True
        # Idempotent second call: token already blacklisted.
        assert adapter.revoke_by_jti(jti=kill_jti) is False
        # Unknown jti: nothing to do.
        assert adapter.revoke_by_jti(jti="no-such-jti") is False

        blacklisted = set(BlacklistedToken.objects.filter(token__user=user).values_list("token__jti", flat=True))
        assert blacklisted == {kill_jti}
        assert OutstandingToken.objects.filter(jti=keep_jti).exists()


class TestLogoutRevokesSession:
    def test_single_device_logout_revokes_exactly_that_session(self, api_client):
        user = _make_user("logout-single@example.com")
        first = _login(api_client, user).data["tokens"]
        second = _login(api_client, user).data["tokens"]
        first_jti = str(RefreshToken(first["refresh"])["jti"])
        second_jti = str(RefreshToken(second["refresh"])["jti"])

        api_client.force_authenticate(user=user)
        response = api_client.post(reverse("logout"), {"refresh": second["refresh"]}, format="json")
        assert response.status_code == 204

        revoked = UserSession.objects.get(refresh_jti=second_jti)
        assert revoked.revoked_at is not None
        assert revoked.revoked_reason == "logout"
        survivor = UserSession.objects.get(refresh_jti=first_jti)
        assert survivor.revoked_at is None

    def test_all_devices_logout_revokes_every_session(self, api_client):
        user = _make_user("logout-all@example.com")
        _login(api_client, user)
        tokens = _login(api_client, user).data["tokens"]

        api_client.force_authenticate(user=user)
        response = api_client.post(
            reverse("logout"),
            {"refresh": tokens["refresh"], "all_devices": True},
            format="json",
        )
        assert response.status_code == 204

        assert UserSession.objects.filter(user=user).count() == 2
        assert not UserSession.objects.filter(user=user, revoked_at__isnull=True).exists()
        assert set(UserSession.objects.filter(user=user).values_list("revoked_reason", flat=True)) == {"logout"}
