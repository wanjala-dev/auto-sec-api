"""Integration tests: self-serve session endpoints (T2-S3).

GET /identity/me/sessions/, DELETE /identity/me/sessions/<id>/,
POST /identity/me/sessions/revoke-others/ — full stack through HTTP with
real JWTs so the ``sid`` claim drives ``is_current``.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken
from rest_framework_simplejwt.tokens import RefreshToken

from infrastructure.persistence.users.models import AuthAuditEvent, CustomUser, UserSession

pytestmark = pytest.mark.django_db

PASSWORD = "sessions-endpoint-pass-123"


@pytest.fixture(autouse=True)
def disable_security_events_async(settings):
    settings.SECURITY_EVENTS_ASYNC = False


def _make_user(email) -> CustomUser:
    user = CustomUser.objects.create_user(email=email, username=email.split("@")[0], password=PASSWORD)
    user.is_verified = True
    user.save(update_fields=["is_verified"])
    return user


def _login(api_client, user, **extra) -> dict:
    response = api_client.post(reverse("login"), {"email": user.email, "password": PASSWORD}, format="json", **extra)
    assert response.status_code == 200
    return response.data["tokens"]


def _jti(tokens) -> str:
    return str(RefreshToken(tokens["refresh"])["jti"])


def _auth(api_client, tokens):
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")


class TestListMySessions:
    def test_shape_ordering_and_is_current(self, api_client):
        user = _make_user("sessions-list@example.com")
        older = _login(api_client, user, HTTP_USER_AGENT="older-device/1.0")
        current = _login(api_client, user, HTTP_USER_AGENT="current-device/2.0")

        _auth(api_client, current)
        response = api_client.get(reverse("my-sessions"))
        assert response.status_code == 200

        payload = response.data
        assert isinstance(payload, list)
        assert len(payload) == 2

        expected_fields = {
            "id",
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
            "is_current",
        }
        assert set(payload[0].keys()) == expected_fields
        # The refresh jti must never leak.
        assert "refresh_jti" not in payload[0]

        current_session = UserSession.objects.get(refresh_jti=_jti(current))
        older_session = UserSession.objects.get(refresh_jti=_jti(older))
        by_id = {row["id"]: row for row in payload}
        assert by_id[str(current_session.id)]["is_current"] is True
        assert by_id[str(older_session.id)]["is_current"] is False
        assert sum(row["is_current"] for row in payload) == 1
        assert all(row["is_active"] for row in payload)
        assert all(row["login_method"] == "password" for row in payload)

    def test_is_active_flips_for_revoked_and_expired_sessions(self, api_client):
        user = _make_user("sessions-active@example.com")
        revoked = _login(api_client, user)
        expired = _login(api_client, user)
        current = _login(api_client, user)

        now = timezone.now()
        UserSession.objects.filter(refresh_jti=_jti(revoked)).update(revoked_at=now, revoked_reason="logout")
        UserSession.objects.filter(refresh_jti=_jti(expired)).update(expires_at=now - timedelta(minutes=1))

        _auth(api_client, current)
        response = api_client.get(reverse("my-sessions"))
        assert response.status_code == 200

        by_jti = {str(UserSession.objects.get(refresh_jti=_jti(t)).id): t for t in (revoked, expired, current)}
        for row in response.data:
            if row["id"] == str(UserSession.objects.get(refresh_jti=_jti(current)).id):
                assert row["is_active"] is True
            else:
                assert row["is_active"] is False
        assert len(by_jti) == 3

    def test_requires_authentication(self, api_client):
        assert api_client.get(reverse("my-sessions")).status_code == 401

    def test_force_authenticated_client_without_sid_marks_nothing_current(self, api_client):
        user = _make_user("sessions-nosid@example.com")
        _login(api_client, user)
        api_client.force_authenticate(user=user)  # request.auth is None → no sid
        response = api_client.get(reverse("my-sessions"))
        assert response.status_code == 200
        assert all(row["is_current"] is False for row in response.data)


class TestRevokeOneSession:
    def test_revokes_exactly_that_session_and_token(self, api_client):
        user = _make_user("sessions-revoke@example.com")
        victim = _login(api_client, user)
        keeper = _login(api_client, user)
        # Compute jtis up front — RefreshToken() on a blacklisted token raises.
        victim_jti = _jti(victim)
        keeper_jti = _jti(keeper)
        victim_session = UserSession.objects.get(refresh_jti=victim_jti)

        _auth(api_client, keeper)
        response = api_client.delete(reverse("my-session-revoke", kwargs={"session_id": victim_session.id}))
        assert response.status_code == 204

        victim_session.refresh_from_db()
        assert victim_session.revoked_at is not None
        assert victim_session.revoked_reason == "user_revoked"
        keeper_session = UserSession.objects.get(refresh_jti=keeper_jti)
        assert keeper_session.revoked_at is None

        # The victim refresh token is blacklisted → refresh 401s; the
        # keeper's still works.
        refresh_url = reverse("token_refresh")
        assert api_client.post(refresh_url, {"refresh": victim["refresh"]}, format="json").status_code == 401
        assert api_client.post(refresh_url, {"refresh": keeper["refresh"]}, format="json").status_code == 200
        assert BlacklistedToken.objects.filter(token__jti=victim_jti).exists()

        # Audit event recorded and linked to the revoked session.
        event = AuthAuditEvent.objects.filter(user=user, event_code="auth.session_revoked").latest("created_at")
        assert event.success is True
        assert event.metadata["revoked_session_id"] == str(victim_session.id)
        assert event.session_id == victim_session.id

    def test_revoking_twice_is_idempotent_204(self, api_client):
        user = _make_user("sessions-idem@example.com")
        victim = _login(api_client, user)
        keeper = _login(api_client, user)
        victim_session = UserSession.objects.get(refresh_jti=_jti(victim))

        _auth(api_client, keeper)
        url = reverse("my-session-revoke", kwargs={"session_id": victim_session.id})
        assert api_client.delete(url).status_code == 204
        assert api_client.delete(url).status_code == 204
        # No duplicate audit event for the no-op second call.
        assert AuthAuditEvent.objects.filter(user=user, event_code="auth.session_revoked").count() == 1

    def test_another_users_session_is_404(self, api_client):
        owner = _make_user("sessions-owner@example.com")
        attacker = _make_user("sessions-attacker@example.com")
        owner_tokens = _login(api_client, owner)
        owner_session = UserSession.objects.get(refresh_jti=_jti(owner_tokens))
        attacker_tokens = _login(api_client, attacker)

        _auth(api_client, attacker_tokens)
        response = api_client.delete(reverse("my-session-revoke", kwargs={"session_id": owner_session.id}))
        assert response.status_code == 404
        owner_session.refresh_from_db()
        assert owner_session.revoked_at is None

    def test_unknown_session_id_is_404(self, api_client):
        import uuid

        user = _make_user("sessions-unknown@example.com")
        tokens = _login(api_client, user)
        _auth(api_client, tokens)
        response = api_client.delete(reverse("my-session-revoke", kwargs={"session_id": uuid.uuid4()}))
        assert response.status_code == 404


class TestRevokeOtherSessions:
    def test_revokes_all_but_current(self, api_client):
        user = _make_user("sessions-others@example.com")
        first = _login(api_client, user)
        second = _login(api_client, user)
        current = _login(api_client, user)
        # Compute jtis up front — RefreshToken() on a blacklisted token raises.
        first_jti, second_jti, current_jti = _jti(first), _jti(second), _jti(current)

        _auth(api_client, current)
        response = api_client.post(reverse("my-sessions-revoke-others"))
        assert response.status_code == 200
        assert response.data == {"revoked": 2}

        current_session = UserSession.objects.get(refresh_jti=current_jti)
        assert current_session.revoked_at is None
        for jti in (first_jti, second_jti):
            session = UserSession.objects.get(refresh_jti=jti)
            assert session.revoked_at is not None
            assert session.revoked_reason == "user_revoked"

        refresh_url = reverse("token_refresh")
        assert api_client.post(refresh_url, {"refresh": current["refresh"]}, format="json").status_code == 200
        assert api_client.post(refresh_url, {"refresh": first["refresh"]}, format="json").status_code == 401
        assert api_client.post(refresh_url, {"refresh": second["refresh"]}, format="json").status_code == 401

    def test_token_without_sid_claim_is_400(self, api_client):
        user = _make_user("sessions-others-nosid@example.com")
        _login(api_client, user)
        api_client.force_authenticate(user=user)  # request.auth None → no sid claim
        response = api_client.post(reverse("my-sessions-revoke-others"))
        assert response.status_code == 400
        # Nothing revoked.
        assert not UserSession.objects.filter(user=user, revoked_at__isnull=False).exists()
