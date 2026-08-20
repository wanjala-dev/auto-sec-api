"""Every path that mints a session must honour the user's second factor.

``LoginUseCase`` withholds the token pair when the user has 2FA armed and hands
back a short-lived challenge instead (``otp_required`` / ``preauth_token``). That
contract is only worth something if it holds on EVERY door into the product.

It did not. ``requires_otp`` was consulted in exactly one place — the password
login — so the passwordless paths walked straight past it:

* ``POST /identity/magic-link/verify/`` returned a full ``access`` + ``refresh``
  pair with ``otp_verified: False`` for a TOTP-armed account. Anyone who could
  read the account's inbox held the product, and the second factor — the control
  that exists precisely because a password or a mailbox may be compromised —
  never entered the picture.
* ``POST /identity/google/`` hardcoded ``"otp_required": False`` in its response.

These tests pin the gate on each mint path, and pin that finishing the challenge
still gets you in.
"""

import pytest
from django.urls import reverse
from django_otp.plugins.otp_totp.models import TOTPDevice

from components.identity.application.providers.magic_link_provider import (
    get_magic_link_provider,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def two_factor_user(user_factory):
    """A verified user with 2FA armed on a confirmed TOTP device."""
    user = user_factory(password="pass1234")
    user.is_verified = True
    user.two_factor_enabled = True
    user.save(update_fields=["is_verified", "two_factor_enabled"])
    TOTPDevice.objects.create(user=user, confirmed=True)
    return user


def _mint_magic_link(email: str) -> str:
    """Mint a link through the product's own port — never a hand-made token."""
    store = get_magic_link_provider().store()
    minted = store.mint_token(email=email, next_url="", ttl_minutes=15)
    assert minted is not None
    return minted.token


# ── Magic link ───────────────────────────────────────────────────────


def test_magic_link_does_not_mint_a_session_for_a_two_factor_user(api_client, two_factor_user, settings):
    """Inbox control must not be enough when a second factor is armed."""
    settings.SECURITY_EVENTS_ASYNC = False
    token = _mint_magic_link(two_factor_user.email)

    response = api_client.post(reverse("magic-link-verify"), {"token": token}, format="json")

    assert response.status_code == 200, response.data
    assert response.data.get("otp_required") is True, (
        "magic-link verify issued a session without the second factor — 2FA is bypassable "
        "by anyone who can read the inbox"
    )
    assert not response.data.get("tokens"), (
        f"magic-link verify handed out {sorted((response.data.get('tokens') or {}).keys())} "
        "before the OTP was presented"
    )
    assert response.data.get("preauth_token")


def test_magic_link_challenge_token_authenticates_nothing(api_client, two_factor_user, settings):
    """The challenge it hands back must be as powerless as the login one."""
    settings.SECURITY_EVENTS_ASYNC = False
    token = _mint_magic_link(two_factor_user.email)
    preauth = api_client.post(reverse("magic-link-verify"), {"token": token}, format="json").data["preauth_token"]

    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {preauth}")
    response = api_client.get(reverse("user-summary"))

    assert response.status_code == 401, (
        f"the magic-link challenge token authenticated a protected read (got {response.status_code})"
    )


def test_magic_link_registers_no_session_until_the_otp_is_presented(api_client, two_factor_user, settings):
    """A challenge is not a login — nothing may land in the session registry."""
    from infrastructure.persistence.users.models import UserSession

    settings.SECURITY_EVENTS_ASYNC = False
    token = _mint_magic_link(two_factor_user.email)

    api_client.post(reverse("magic-link-verify"), {"token": token}, format="json")

    assert UserSession.objects.filter(user=two_factor_user).count() == 0, (
        "a login session was registered for a challenge that was never completed"
    )


def test_magic_link_still_signs_in_a_user_without_two_factor(api_client, user_factory, settings):
    """Gating 2FA users must not break the flow for everyone else."""
    settings.SECURITY_EVENTS_ASYNC = False
    user = user_factory(password="pass1234")
    user.is_verified = True
    user.save(update_fields=["is_verified"])
    token = _mint_magic_link(user.email)

    response = api_client.post(reverse("magic-link-verify"), {"token": token}, format="json")

    assert response.status_code == 200, response.data
    assert response.data.get("otp_required") is not True
    assert response.data["tokens"].get("access")


def test_magic_link_challenge_is_completed_by_the_otp_endpoint(api_client, two_factor_user, settings):
    """Finishing the second factor must actually sign the user in.

    A gate that cannot be passed is an outage, not a control.
    """
    from django_otp.oath import totp

    settings.SECURITY_EVENTS_ASYNC = False
    token = _mint_magic_link(two_factor_user.email)
    preauth = api_client.post(reverse("magic-link-verify"), {"token": token}, format="json").data["preauth_token"]

    device = TOTPDevice.objects.get(user=two_factor_user)
    code = str(totp(device.bin_key, step=device.step, t0=device.t0, digits=device.digits)).zfill(device.digits)

    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {preauth}")
    response = api_client.post(reverse("totp-verify"), {"token": code}, format="json")

    assert response.status_code == 200, response.data
    assert response.data["tokens"].get("access")


# ── Google ───────────────────────────────────────────────────────────


GOOGLE_CLIENT_ID = "test-web-client.apps.googleusercontent.com"
_VERIFY_TARGET = "google.oauth2.id_token.verify_oauth2_token"


@pytest.fixture
def google_two_factor_user(user_factory, monkeypatch):
    """A Google-linked account that has since armed a second factor.

    Mocked at the same boundary ``test_google_auth.py`` uses — the Google
    verification library — so everything downstream is the real path.
    """
    monkeypatch.setenv("GOOGLE_CLIENT_ID", GOOGLE_CLIENT_ID)
    monkeypatch.delenv("GOOGLE_CLIENT_IDS", raising=False)

    user = user_factory()
    user.is_verified = True
    user.auth_provider = "google"
    user.google_sub = "google-sub-2fa"
    user.two_factor_enabled = True
    user.set_unusable_password()
    user.save(
        update_fields=["is_verified", "auth_provider", "google_sub", "two_factor_enabled", "password"],
    )
    TOTPDevice.objects.create(user=user, confirmed=True)
    return user


def test_google_sign_in_does_not_mint_a_session_for_a_two_factor_user(api_client, google_two_factor_user, settings):
    """The Google response hardcoded ``otp_required: False``. It must not."""
    from unittest.mock import patch

    settings.SECURITY_EVENTS_ASYNC = False
    claims = {
        "sub": "google-sub-2fa",
        "email": google_two_factor_user.email,
        "email_verified": True,
        "name": "QA Google",
        "aud": GOOGLE_CLIENT_ID,
        "iss": "accounts.google.com",
        "picture": "",
    }

    with patch(_VERIFY_TARGET, return_value=claims):
        response = api_client.post("/identity/google/", {"auth_token": "a.b.c"}, format="json")

    assert response.status_code == 200, response.data
    assert response.data.get("otp_required") is True, "Google sign-in issued a session without the second factor"
    assert not response.data.get("tokens"), (
        f"Google sign-in handed out {sorted((response.data.get('tokens') or {}).keys())} before the OTP was presented"
    )
    assert response.data.get("preauth_token")
