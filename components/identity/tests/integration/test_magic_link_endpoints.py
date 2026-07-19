"""End-to-end coverage for the passwordless magic-link sign-in flow.

This is the post-donation "track this gift" path: an anonymous donor
who gave through a public donate link requests a magic link, clicks
it, and lands authenticated with a populated `/donations/mine` page.

The tests pin down the contracts that are load-bearing for that flow:

1. Request endpoint NEVER reveals whether the email exists. The
   response is identical for known + unknown emails — this is the
   anti-enumeration posture used by password reset.
2. A first-click on a token for an unknown email creates a new
   account, sets ``is_verified=True`` (clicking the link IS the
   ownership proof), and issues a JWT pair.
3. The token is single-use. A second click within the TTL window
   returns 400, not a refreshed session.
4. Expired tokens return 400 — protects against deferred clicks
   (e.g. someone leaves the email in their inbox for a week and
   clicks later).
5. Verify response shape matches LoginAPIView so the frontend
   session plumbing works unchanged.
6. The ``next_url`` is preserved across the round-trip so the
   verify endpoint can land the donor on /donations/mine.
"""
from __future__ import annotations

import secrets
from datetime import timedelta

import pytest
from django.utils import timezone

from infrastructure.persistence.users.models import CustomUser, MagicLinkToken


pytestmark = [pytest.mark.django_db]


class TestMagicLinkRequest:
    def test_returns_200_for_unknown_email(self, api_client):
        response = api_client.post(
            "/identity/magic-link/request/",
            {"email": "stranger@example.com"},
            format="json",
        )

        assert response.status_code == 200
        assert response.data.get("status") == "ok"
        # Token row exists even for unknown emails — the verify side
        # will create the user on click.
        token = MagicLinkToken.objects.filter(
            email="stranger@example.com"
        ).first()
        assert token is not None
        assert token.user is None

    def test_returns_same_response_for_known_email(
        self, api_client, user_factory
    ):
        user_factory(email="known@example.com")

        response = api_client.post(
            "/identity/magic-link/request/",
            {"email": "known@example.com"},
            format="json",
        )

        assert response.status_code == 200
        # Same outer shape as the unknown-email case. Don't assert on
        # the exact message string — that would couple the test to
        # marketing copy. Do assert on the key set, which is the
        # contract.
        assert set(response.data.keys()) == {"status", "message"}

    def test_blank_email_does_not_error(self, api_client):
        # Empty / missing email still returns the generic OK — the
        # anti-enumeration posture means we don't 400 on bad input
        # either.
        response = api_client.post(
            "/identity/magic-link/request/", {}, format="json"
        )

        assert response.status_code == 200
        assert MagicLinkToken.objects.count() == 0

    def test_next_url_is_persisted(self, api_client):
        response = api_client.post(
            "/identity/magic-link/request/",
            {"email": "donor@example.com", "next": "/donations/mine"},
            format="json",
        )

        assert response.status_code == 200
        token = MagicLinkToken.objects.get(email="donor@example.com")
        assert token.next_url == "/donations/mine"

    def test_absolute_next_url_is_stripped(self, api_client):
        # Open-redirect guard: an attacker could craft a request with
        # next=https://evil/steal and the verify view would 302 the
        # newly-authed user off-site. The use case strips anything
        # that isn't a same-site relative path.
        response = api_client.post(
            "/identity/magic-link/request/",
            {"email": "donor@example.com", "next": "https://evil.example/steal"},
            format="json",
        )

        assert response.status_code == 200
        token = MagicLinkToken.objects.get(email="donor@example.com")
        assert token.next_url == ""


class TestMagicLinkVerify:
    def _request_link(self, api_client, email, next_url=""):
        api_client.post(
            "/identity/magic-link/request/",
            {"email": email, "next": next_url},
            format="json",
        )
        token = MagicLinkToken.objects.get(email=email)
        return token

    def test_first_click_creates_user_and_returns_tokens(self, api_client):
        token = self._request_link(api_client, "new@example.com")

        response = api_client.post(
            "/identity/magic-link/verify/",
            {"token": token.token},
            format="json",
        )

        assert response.status_code == 200, response.data
        data = response.data
        assert data["email"] == "new@example.com"
        assert data["tokens"]["access"]
        assert data["tokens"]["refresh"]
        assert data["created_user"] is True
        # User was actually created, is verified, and has unusable
        # password (so the password-login path can't be used until
        # they explicitly set one via password-reset).
        user = CustomUser.objects.get(email="new@example.com")
        assert user.is_verified is True
        assert user.has_usable_password() is False

    def test_response_shape_matches_login(self, api_client):
        # Frontend session plumbing depends on these exact keys —
        # they mirror LoginAPIView. Any drift here is a downstream
        # breakage for ``useViewerSession``.
        token = self._request_link(api_client, "shape@example.com")

        response = api_client.post(
            "/identity/magic-link/verify/",
            {"token": token.token},
            format="json",
        )

        assert response.status_code == 200
        required = {
            "pk",
            "user_id",
            "email",
            "username",
            "is_onboard_complete",
            "is_contributor",
            "tokens",
            "next_url",
            "created_user",
        }
        missing = required - set(response.data.keys())
        assert not missing, f"verify response missing keys: {missing}"
        assert set(response.data["tokens"].keys()) == {"access", "refresh"}

    def test_known_user_is_returned_not_recreated(
        self, api_client, user_factory
    ):
        existing = user_factory(email="known@example.com")
        token = self._request_link(api_client, "known@example.com")

        response = api_client.post(
            "/identity/magic-link/verify/",
            {"token": token.token},
            format="json",
        )

        assert response.status_code == 200
        assert response.data["user_id"] == str(existing.id)
        assert response.data["created_user"] is False
        # Still only one user with that email — no accidental dup.
        assert CustomUser.objects.filter(email="known@example.com").count() == 1

    def test_token_is_single_use(self, api_client):
        token = self._request_link(api_client, "replay@example.com")

        first = api_client.post(
            "/identity/magic-link/verify/",
            {"token": token.token},
            format="json",
        )
        second = api_client.post(
            "/identity/magic-link/verify/",
            {"token": token.token},
            format="json",
        )

        assert first.status_code == 200
        assert second.status_code == 400
        assert second.data.get("code") == "invalid_token"

    def test_expired_token_is_rejected(self, api_client):
        token = MagicLinkToken.objects.create(
            token=secrets.token_urlsafe(32),
            email="late@example.com",
            expires_at=timezone.now() - timedelta(seconds=1),
        )

        response = api_client.post(
            "/identity/magic-link/verify/",
            {"token": token.token},
            format="json",
        )

        assert response.status_code == 400
        assert response.data.get("code") == "invalid_token"
        token.refresh_from_db()
        # Expired tokens are NOT marked consumed — they're just
        # filtered out by the WHERE clause, so the row stays around
        # for audit (or cleanup by a future scheduled task).
        assert token.consumed_at is None

    def test_unknown_token_returns_400(self, api_client):
        response = api_client.post(
            "/identity/magic-link/verify/",
            {"token": "not-a-real-token-anywhere"},
            format="json",
        )

        assert response.status_code == 400
        assert response.data.get("code") == "invalid_token"

    def test_missing_token_returns_400(self, api_client):
        response = api_client.post(
            "/identity/magic-link/verify/", {}, format="json"
        )

        assert response.status_code == 400
        assert response.data.get("code") == "invalid_token"

    def test_next_url_round_trips_through_verify(self, api_client):
        token = self._request_link(
            api_client, "redirect@example.com", next_url="/donations/mine"
        )

        response = api_client.post(
            "/identity/magic-link/verify/",
            {"token": token.token},
            format="json",
        )

        assert response.status_code == 200
        assert response.data["next_url"] == "/donations/mine"
