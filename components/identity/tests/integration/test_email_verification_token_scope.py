"""The email-verification link's token must ONLY be able to verify an email.

Registration emails a confirmation link. That link used to carry a plain
``rest_framework_simplejwt.tokens.AccessToken`` — the *same* credential the
login endpoint hands out — with the full ``ACCESS_TOKEN_LIFETIME`` (10 days in
dev, 1 day in prod). Anyone holding the link therefore held a full-privilege
session:

* it authenticated every ``IsAuthenticated`` read and write in the product;
* it authenticated the Channels WebSocket handshake;
* it did so on an account whose email was still UNVERIFIED — the very gate
  ``LoginUseCase`` refuses to pass ("Email is not verified"), so the link was a
  side door around the verification gate it was supposed to close;
* and it travelled by plaintext email, through every relay and inbox on the way.

The fix is the structural one this codebase already proved on the login
pre-auth token (``otp_challenge_token.py`` / PR #406): give the token a distinct
``token_type`` so ``JWTAuthentication`` — which only decodes the classes in
``SIMPLE_JWT["AUTH_TOKEN_CLASSES"]`` — refuses it by construction, everywhere,
with no allowlist to keep in sync.

These tests pin the contract from both sides: powerless as a credential,
still able to verify the email it was minted for.
"""

import pytest
from django.urls import reverse

from components.identity.application.providers.identity_provider import IdentityProvider

pytestmark = pytest.mark.django_db


@pytest.fixture
def unverified_user(user_factory):
    """A freshly registered user — created, but email not yet confirmed."""
    user = user_factory(password="pass1234")
    user.is_verified = False
    user.save(update_fields=["is_verified"])
    return user


def _verification_token_from_email(user, mailoutbox) -> str:
    """Drive the real send path and read the token out of the sent email.

    This is the product minting the credential exactly as registration does —
    no hand-crafted token (see ``.claude/rules`` on never forging a JWT).
    """
    import re

    mailoutbox.clear()
    use_case = IdentityProvider.build_send_verification_email_use_case()
    outcome = use_case.execute(
        user_id=user.id,
        confirmation_base_url="https://example.test/identity/email-confirmed",
        site_name="Auto-Sec",
        site_domain="example.test",
    )
    assert outcome == "sent"
    assert mailoutbox, "registration sent no verification email"
    match = re.search(r"token=([A-Za-z0-9._-]+)", mailoutbox[0].body)
    assert match, "verification email carried no token"
    return match.group(1)


# ── The bypass: the emailed token must not authenticate anything ─────


@pytest.mark.parametrize("url_name", ["user-summary", "notifications:notification-list"])
def test_verification_token_is_rejected_by_authenticated_read_endpoints(
    api_client, unverified_user, mailoutbox, url_name
):
    """A link sitting in an inbox must not be a read session."""
    token = _verification_token_from_email(unverified_user, mailoutbox)

    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    response = api_client.get(reverse(url_name))

    assert response.status_code == 401, (
        f"{url_name} accepted the email-verification token — the confirmation link is a "
        f"full session (got {response.status_code})"
    )


def test_verification_token_is_rejected_by_authenticated_write_endpoint(api_client, unverified_user, mailoutbox):
    """And it must certainly not be a WRITE session."""
    original_username = unverified_user.username
    token = _verification_token_from_email(unverified_user, mailoutbox)

    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    response = api_client.patch(
        reverse("user-base-edit", kwargs={"uuid": str(unverified_user.id)}),
        {"username": "pwned-by-link"},
        format="json",
    )

    assert response.status_code == 401, f"the email-verification token performed a WRITE (got {response.status_code})"
    unverified_user.refresh_from_db()
    assert unverified_user.username == original_username


def test_verification_token_is_not_an_access_token(unverified_user, mailoutbox):
    """The structural guarantee: the default auth path cannot even decode it.

    ``JWTAuthentication.get_validated_token`` sweeps only
    ``SIMPLE_JWT["AUTH_TOKEN_CLASSES"]``. A distinct ``token_type`` is what makes
    the rejection total — including the Channels WebSocket middleware, which
    shares that code path and has no allowlist of its own.
    """
    from rest_framework_simplejwt.authentication import JWTAuthentication
    from rest_framework_simplejwt.exceptions import InvalidToken, TokenError

    token = _verification_token_from_email(unverified_user, mailoutbox)

    with pytest.raises((InvalidToken, TokenError)):
        JWTAuthentication().get_validated_token(token.encode())


def test_verification_token_lifetime_is_independent_of_the_access_lifetime(unverified_user, mailoutbox, settings):
    """A confirmation link lives in an inbox — it must not carry a 10-day session.

    ``ACCESS_TOKEN_LIFETIME`` is pushed to the value the dev/local settings
    actually ship (10 days) so the assertion proves DECOUPLING rather than
    passing on whatever the test settings happen to configure. That coupling is
    precisely what made the emailed credential long-lived in the first place.
    """
    import base64
    import json
    from datetime import timedelta

    settings.SIMPLE_JWT = {**getattr(settings, "SIMPLE_JWT", {}), "ACCESS_TOKEN_LIFETIME": timedelta(days=10)}

    token = _verification_token_from_email(unverified_user, mailoutbox)
    payload = token.split(".")[1]
    payload += "=" * (-len(payload) % 4)
    claims = json.loads(base64.urlsafe_b64decode(payload))

    lifetime_seconds = claims["exp"] - claims["iat"]
    assert lifetime_seconds <= 24 * 3600, (
        f"verification token lives {lifetime_seconds / 3600:.1f}h — an emailed credential must be short-lived"
    )


# ── The contract it must keep: it still verifies the email ───────────


def test_verification_token_still_verifies_the_email(api_client, unverified_user, mailoutbox):
    """Locking the token down must not break the flow it exists for."""
    token = _verification_token_from_email(unverified_user, mailoutbox)

    response = api_client.get(reverse("email-verify"), {"token": token})

    assert response.status_code == 200, response.data
    unverified_user.refresh_from_db()
    assert unverified_user.is_verified is True


def test_an_access_token_cannot_stand_in_for_a_verification_token(api_client, unverified_user, mailoutbox):
    """Scope cuts both ways: a session credential must not verify an email.

    The decode path used to be a bare ``jwt.decode`` that read ``user_id`` and
    ignored ``token_type``, so any token signed with the app key — access,
    refresh, or the OTP challenge — was accepted as proof of inbox control.
    """
    tokens = IdentityProvider.build_token_adapter().issue_tokens(
        unverified_user.id,
        otp_verified=False,
        device_id=None,
        include_refresh=False,
    )

    response = api_client.get(reverse("email-verify"), {"token": tokens.access})

    assert response.status_code == 400, f"a plain access token verified an email address (got {response.status_code})"
    unverified_user.refresh_from_db()
    assert unverified_user.is_verified is False
