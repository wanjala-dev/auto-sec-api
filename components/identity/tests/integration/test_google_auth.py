"""End-to-end coverage for the Google (OIDC) sign-in flow.

The frontend hands us a Google ID token (the ``credential`` from Google
Identity Services); we verify it and return a JWT session in the same
shape ``LoginAPIView`` returns. These tests pin the load-bearing
contracts and, crucially, the security posture that replaced the old
shared-``SOCIAL_SECRET`` implementation:

1. First sign-in creates a passwordless account (``auth_provider=google``,
   ``google_sub`` stored, ``is_verified=True``, NO usable password) and
   issues a JWT pair.
2. Returning users are linked by the stable Google ``sub`` — even if
   their Google email changed — so exactly one account results.
3. A pre-existing email/password account is NOT silently taken over by a
   Google token for the same email (409 provider_conflict).
4. An unverified Google email is rejected and creates no account.
5. Audience + issuer are enforced: a genuine token minted for a
   different app, or with a spoofed issuer, is rejected.
6. A malformed / bad-signature token (library raises ValueError) is a
   clean 401, not a 500.

The Google verification library is mocked at the boundary
(``google.oauth2.id_token.verify_oauth2_token``) so no live token is
needed — that's the whole reason verification lives behind a port.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from infrastructure.persistence.users.models import CustomUser, UserProfile

pytestmark = [pytest.mark.django_db]

_VERIFY_TARGET = "google.oauth2.id_token.verify_oauth2_token"
GOOGLE_CLIENT_ID = "test-web-client.apps.googleusercontent.com"


def _claims(
    *,
    sub="google-sub-123",
    email="newuser@example.com",
    email_verified=True,
    name="New User",
    aud=GOOGLE_CLIENT_ID,
    iss="accounts.google.com",
    picture="",
):
    return {
        "sub": sub,
        "email": email,
        "email_verified": email_verified,
        "name": name,
        "aud": aud,
        "iss": iss,
        "picture": picture,
    }


@pytest.fixture(autouse=True)
def google_env(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", GOOGLE_CLIENT_ID)
    monkeypatch.delenv("GOOGLE_CLIENT_IDS", raising=False)


def _post(api_client, token="a.b.c"):
    return api_client.post(
        "/identity/google/", {"auth_token": token}, format="json"
    )


class TestGoogleSignInSuccess:
    def test_new_user_created_passwordless_with_tokens(self, api_client):
        with patch(_VERIFY_TARGET, return_value=_claims()):
            resp = _post(api_client)

        assert resp.status_code == 200, resp.data
        assert resp.data["tokens"]["access"]
        assert resp.data["tokens"]["refresh"]
        assert resp.data["created_user"] is True
        assert resp.data["otp_required"] is False

        user = CustomUser.objects.get(email="newuser@example.com")
        assert user.auth_provider == "google"
        assert user.google_sub == "google-sub-123"
        assert user.is_verified is True
        # The core security guarantee: no password can ever log this
        # user in through the email/password endpoint.
        assert user.has_usable_password() is False

    def test_returning_user_linked_by_sub_even_if_email_changed(
        self, api_client
    ):
        with patch(_VERIFY_TARGET, return_value=_claims()):
            first = _post(api_client)
        assert first.status_code == 200

        # Same Google account (sub) but the user changed their Google
        # email — must resolve to the SAME local account.
        with patch(
            _VERIFY_TARGET,
            return_value=_claims(email="changed@example.com"),
        ):
            second = _post(api_client)

        assert second.status_code == 200
        assert second.data["created_user"] is False
        assert CustomUser.objects.filter(
            google_sub="google-sub-123"
        ).count() == 1


class TestGoogleSignInRejections:
    def test_existing_password_account_not_taken_over(
        self, api_client, user_factory
    ):
        user_factory(email="pwuser@example.com")  # default auth_provider=email

        with patch(
            _VERIFY_TARGET,
            return_value=_claims(email="pwuser@example.com", sub="sub-x"),
        ):
            resp = _post(api_client)

        assert resp.status_code == 409
        assert resp.data["code"] == "provider_conflict"
        # The password account is untouched.
        existing = CustomUser.objects.get(email="pwuser@example.com")
        assert existing.auth_provider == "email"
        assert existing.google_sub is None

    def test_unverified_email_rejected_and_no_account_created(
        self, api_client
    ):
        with patch(
            _VERIFY_TARGET,
            return_value=_claims(
                email="unverified@example.com", email_verified=False
            ),
        ):
            resp = _post(api_client)

        assert resp.status_code == 401
        assert resp.data["code"] == "email_unverified"
        assert not CustomUser.objects.filter(
            email="unverified@example.com"
        ).exists()

    def test_wrong_audience_rejected(self, api_client):
        # Genuine, signed Google token — but minted for a DIFFERENT app.
        with patch(
            _VERIFY_TARGET,
            return_value=_claims(aud="someone-else.apps.googleusercontent.com"),
        ):
            resp = _post(api_client)

        assert resp.status_code == 401
        assert resp.data["code"] == "invalid_token"
        assert CustomUser.objects.count() == 0

    def test_spoofed_issuer_rejected(self, api_client):
        with patch(
            _VERIFY_TARGET,
            return_value=_claims(iss="accounts.google.com.evil.com"),
        ):
            resp = _post(api_client)

        assert resp.status_code == 401
        assert resp.data["code"] == "invalid_token"

    def test_bad_signature_is_401_not_500(self, api_client):
        # The google-auth library raises ValueError for any untrusted
        # token; we must map that to a clean 401.
        with patch(_VERIFY_TARGET, side_effect=ValueError("bad signature")):
            resp = _post(api_client)

        assert resp.status_code == 401
        assert resp.data["code"] == "invalid_token"

    def test_missing_token_is_400(self, api_client):
        resp = api_client.post("/identity/google/", {}, format="json")
        assert resp.status_code == 400


class TestGoogleProfilePhoto:
    _PIC = "https://lh3.googleusercontent.com/a/AGoogleAvatarHash=s96-c"

    def test_new_user_gets_google_photo(self, api_client):
        with patch(_VERIFY_TARGET, return_value=_claims(picture=self._PIC)):
            resp = _post(api_client)

        assert resp.status_code == 200
        profile = UserProfile.objects.get(user__email="newuser@example.com")
        assert profile.photo_url == self._PIC

    def test_existing_photo_not_overwritten(self, api_client):
        # First sign-in sets the Google photo.
        with patch(_VERIFY_TARGET, return_value=_claims(picture=self._PIC)):
            _post(api_client)
        profile = UserProfile.objects.get(user__email="newuser@example.com")
        profile.photo_url = "https://example.com/my-own-avatar.png"
        profile.save(update_fields=["photo_url"])

        # A later sign-in must NOT stomp the user's own avatar.
        with patch(
            _VERIFY_TARGET,
            return_value=_claims(picture="https://lh3.googleusercontent.com/a/NEW=s96-c"),
        ):
            _post(api_client)

        profile.refresh_from_db()
        assert profile.photo_url == "https://example.com/my-own-avatar.png"

    def test_empty_photo_backfilled_on_login(self, api_client):
        # First sign-in with no picture → profile has no photo.
        with patch(_VERIFY_TARGET, return_value=_claims(picture="")):
            _post(api_client)
        profile = UserProfile.objects.get(user__email="newuser@example.com")
        assert not (profile.photo_url or "")

        # Later sign-in now carries a picture → backfilled.
        with patch(_VERIFY_TARGET, return_value=_claims(picture=self._PIC)):
            _post(api_client)

        profile.refresh_from_db()
        assert profile.photo_url == self._PIC
