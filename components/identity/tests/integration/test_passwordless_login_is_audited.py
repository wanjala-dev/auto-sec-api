"""Every way into the product must show up in the login audit trail.

``/identity/me/login-activity/`` and the org-level login-activity view are how a
user or an admin answers "who signed in, from where, when". They read
``AuthAuditEvent``. A password login writes one; the passwordless paths did not.

So a magic-link sign-in created a real session — listed in
``/identity/me/sessions/``, minting real tokens — while the trail that claims to
show sign-ins showed nothing. Confirmed live before this fix: after one
magic-link sign-in the user's session count went 9 → 10 and their ``auth.login``
event count stayed at 9. Google sign-in had the same gap.

For a security product whose audit trail is part of the pitch, a feed that
silently omits a whole category of sign-in is worse than no feed: it reads as
"nobody else signed in" when someone did. That is the defect class this repo
calls a provenance falsehood — the artifact's factual claim is untrue.
"""

from __future__ import annotations

import pytest
from django.urls import reverse

from components.identity.application.providers.magic_link_provider import (
    get_magic_link_provider,
)
from infrastructure.persistence.users.models import AuthAuditEvent

pytestmark = pytest.mark.django_db

GOOGLE_CLIENT_ID = "test-web-client.apps.googleusercontent.com"
_VERIFY_TARGET = "google.oauth2.id_token.verify_oauth2_token"


def _login_events(user):
    return AuthAuditEvent.objects.filter(user=user, event_code="auth.login", success=True)


@pytest.fixture
def verified_user(user_factory):
    user = user_factory(password="pass1234")
    user.is_verified = True
    user.save(update_fields=["is_verified"])
    return user


# ── The password baseline this must match ────────────────────────────


def test_a_password_login_is_audited(api_client, verified_user, settings):
    """The behaviour the passwordless paths have to match."""
    settings.SECURITY_EVENTS_ASYNC = False

    api_client.post(
        reverse("login"),
        {"email": verified_user.email, "password": "pass1234"},
        format="json",
    )

    assert _login_events(verified_user).count() == 1


# ── Magic link ───────────────────────────────────────────────────────


def test_a_magic_link_sign_in_is_audited(api_client, verified_user, settings):
    settings.SECURITY_EVENTS_ASYNC = False
    store = get_magic_link_provider().store()
    token = store.mint_token(email=verified_user.email, next_url="", ttl_minutes=15).token

    response = api_client.post(reverse("magic-link-verify"), {"token": token}, format="json")
    assert response.status_code == 200, response.data
    assert response.data["tokens"].get("access")

    assert _login_events(verified_user).count() == 1, (
        "a magic-link sign-in created a session but left no auth.login event — the login "
        "activity feed silently omits it"
    )


def test_a_magic_link_sign_in_names_its_method(api_client, verified_user, settings):
    """An operator reading the trail must be able to tell HOW someone got in.

    A magic-link sign-in and a password sign-in are not equally interesting
    after a mailbox compromise.
    """
    settings.SECURITY_EVENTS_ASYNC = False
    store = get_magic_link_provider().store()
    token = store.mint_token(email=verified_user.email, next_url="", ttl_minutes=15).token

    api_client.post(reverse("magic-link-verify"), {"token": token}, format="json")

    event = _login_events(verified_user).first()
    assert (event.metadata or {}).get("login_method") == "magic_link"


def test_a_magic_link_sign_in_shows_up_in_the_login_activity_feed(api_client, verified_user, settings):
    """The end-to-end claim, asserted on the surface a user actually reads."""
    settings.SECURITY_EVENTS_ASYNC = False
    store = get_magic_link_provider().store()
    token = store.mint_token(email=verified_user.email, next_url="", ttl_minutes=15).token

    access = api_client.post(reverse("magic-link-verify"), {"token": token}, format="json").data["tokens"]["access"]

    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
    feed = api_client.get(reverse("my-login-activity"))

    assert feed.status_code == 200, feed.data
    rows = feed.data["results"] if isinstance(feed.data, dict) else feed.data
    assert any(r["event_code"] == "auth.login" for r in rows), (
        "the user's own login-activity feed does not show the sign-in they just performed"
    )


def test_a_magic_link_challenge_is_not_audited_as_a_login(api_client, user_factory, settings):
    """A 2FA challenge is not a sign-in. Auditing it as one would be a lie too."""
    from django_otp.plugins.otp_totp.models import TOTPDevice

    settings.SECURITY_EVENTS_ASYNC = False
    user = user_factory(password="pass1234")
    user.is_verified = True
    user.two_factor_enabled = True
    user.save(update_fields=["is_verified", "two_factor_enabled"])
    TOTPDevice.objects.create(user=user, confirmed=True)

    store = get_magic_link_provider().store()
    token = store.mint_token(email=user.email, next_url="", ttl_minutes=15).token

    response = api_client.post(reverse("magic-link-verify"), {"token": token}, format="json")
    assert response.data.get("otp_required") is True

    assert _login_events(user).count() == 0


# ── Google ───────────────────────────────────────────────────────────


def test_a_google_sign_in_is_audited(api_client, user_factory, settings, monkeypatch):
    from unittest.mock import patch

    monkeypatch.setenv("GOOGLE_CLIENT_ID", GOOGLE_CLIENT_ID)
    monkeypatch.delenv("GOOGLE_CLIENT_IDS", raising=False)
    settings.SECURITY_EVENTS_ASYNC = False

    user = user_factory()
    user.is_verified = True
    user.auth_provider = "google"
    user.google_sub = "google-sub-audit"
    user.set_unusable_password()
    user.save(update_fields=["is_verified", "auth_provider", "google_sub", "password"])

    claims = {
        "sub": "google-sub-audit",
        "email": user.email,
        "email_verified": True,
        "name": "QA Google",
        "aud": GOOGLE_CLIENT_ID,
        "iss": "accounts.google.com",
        "picture": "",
    }
    with patch(_VERIFY_TARGET, return_value=claims):
        response = api_client.post("/identity/google/", {"auth_token": "a.b.c"}, format="json")

    assert response.status_code == 200, response.data
    assert _login_events(user).count() == 1, "a Google sign-in left no auth.login event"
    assert (_login_events(user).first().metadata or {}).get("login_method") == "google"
