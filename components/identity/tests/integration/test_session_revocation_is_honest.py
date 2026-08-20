"""Revoking a session must actually end it.

Every revocation surface in the product reported success while the access token
it claimed to kill kept working:

* ``POST /identity/logout/`` → 204, access token still 200
* ``DELETE /identity/me/sessions/<id>/`` → 204, that session's token still 200
* ``POST /identity/me/sessions/revoke-others/`` → ``{"revoked": 3}``, still 200
* ``PUT /identity/changepassword/`` → 200, old access AND refresh still 200
* ``PATCH /identity/password-reset-complete`` → 200, old access AND refresh still 200

The refresh side was already handled (logout and the revoke endpoints blacklist
the refresh token). The hole was the ACCESS token: a stateless JWT that nothing
checked against the session registry, so it stayed valid until ``exp`` — ten days
on dev/local, one day in prod. Password reset is the sharpest case: it is the
flow a compromised user runs, and it left the attacker holding a working session
plus a refresh token that kept minting new ones for the full refresh lifetime.

The registry needed to close this already existed: ``issue_tokens`` stamps a
``sid`` claim on both tokens carrying the refresh jti, and ``UserSession`` has
``revoked_at``. Nothing read them on the request path. Now
``SessionAwareJWTAuthentication`` does.
"""

from __future__ import annotations

import pytest
from django.urls import reverse

from infrastructure.persistence.users.models import UserSession

pytestmark = pytest.mark.django_db

PASSWORD = "SessProbe2026!aa"


@pytest.fixture
def live_user(user_factory):
    user = user_factory(password=PASSWORD)
    user.is_verified = True
    user.save(update_fields=["is_verified"])
    return user


def _login(api_client, user, settings) -> tuple[str, str]:
    """Drive the real login endpoint; return (access, refresh)."""
    settings.SECURITY_EVENTS_ASYNC = False
    api_client.credentials()
    response = api_client.post(
        reverse("login"),
        {"email": user.email, "password": PASSWORD},
        format="json",
    )
    assert response.status_code == 200, response.data
    tokens = response.data["tokens"]
    return tokens["access"], tokens["refresh"]


def _protected_read(api_client, access: str) -> int:
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
    return api_client.get(reverse("user-summary")).status_code


def _refresh(api_client, refresh: str) -> int:
    api_client.credentials()
    return api_client.post(reverse("token_refresh"), {"refresh": refresh}, format="json").status_code


# ── Logout ───────────────────────────────────────────────────────────


def test_logout_actually_ends_the_access_token(api_client, live_user, settings):
    access, refresh = _login(api_client, live_user, settings)
    assert _protected_read(api_client, access) == 200

    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
    assert api_client.post(reverse("logout"), {"refresh": refresh}, format="json").status_code == 204

    assert _protected_read(api_client, access) == 401, (
        "logout reported success but the access token still authenticates"
    )


# ── Revoke one session ───────────────────────────────────────────────


def test_revoking_a_session_ends_that_session_s_access_token(api_client, live_user, settings):
    victim_access, _ = _login(api_client, live_user, settings)
    other_access, _ = _login(api_client, live_user, settings)

    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {victim_access}")
    session_id = [s["id"] for s in api_client.get(reverse("my-sessions")).data if s["is_current"]][0]

    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {other_access}")
    assert api_client.delete(reverse("my-session-revoke", kwargs={"session_id": session_id})).status_code == 204

    assert _protected_read(api_client, victim_access) == 401, (
        "revoke-session reported success but the revoked session's token still authenticates"
    )
    assert _protected_read(api_client, other_access) == 200, "the revoking session was killed too"


# ── Revoke others ────────────────────────────────────────────────────


def test_revoke_others_ends_the_other_sessions_access_tokens(api_client, live_user, settings):
    stale_access, _ = _login(api_client, live_user, settings)
    current_access, _ = _login(api_client, live_user, settings)

    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {current_access}")
    assert api_client.post(reverse("my-sessions-revoke-others"), {}, format="json").status_code == 200

    assert _protected_read(api_client, stale_access) == 401, (
        "revoke-others reported a revoked count but the other session's token still authenticates"
    )
    assert _protected_read(api_client, current_access) == 200, "revoke-others killed the current session"


# ── Password change ──────────────────────────────────────────────────


def test_changing_the_password_ends_the_other_sessions(api_client, live_user, settings):
    """The whole point of changing a password is ending whoever else has it."""
    attacker_access, attacker_refresh = _login(api_client, live_user, settings)
    owner_access, _ = _login(api_client, live_user, settings)

    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {owner_access}")
    response = api_client.put(
        reverse("change-password"),
        {
            "old_password": PASSWORD,
            "new_password": "SessProbe2026!bb",
            "confirm_password": "SessProbe2026!bb",
        },
        format="json",
    )
    assert response.status_code == 200, response.data

    assert _protected_read(api_client, attacker_access) == 401, (
        "password change left every other session working — a compromised account stays compromised"
    )
    assert _refresh(api_client, attacker_refresh) == 401, (
        "password change left the other session's refresh token minting new access tokens"
    )
    assert _protected_read(api_client, owner_access) == 200, (
        "the session that performed the change was logged out of itself"
    )


# ── Password reset ───────────────────────────────────────────────────


def test_resetting_the_password_ends_every_session(api_client, live_user, settings):
    """Reset is the recovery flow. Nothing may survive it."""
    from django.contrib.auth.tokens import PasswordResetTokenGenerator
    from django.utils.encoding import smart_bytes
    from django.utils.http import urlsafe_base64_encode

    attacker_access, attacker_refresh = _login(api_client, live_user, settings)

    uidb64 = urlsafe_base64_encode(smart_bytes(live_user.id))
    token = PasswordResetTokenGenerator().make_token(live_user)

    api_client.credentials()
    response = api_client.patch(
        "/identity/password-reset-complete",
        {"password": "SessProbe2026!cc", "token": token, "uidb64": uidb64},
        format="json",
    )
    assert response.status_code == 200, response.data

    assert _protected_read(api_client, attacker_access) == 401, (
        "password reset left the attacker's session working — the recovery flow recovers nothing"
    )
    assert _refresh(api_client, attacker_refresh) == 401, (
        "password reset left the attacker's refresh token minting new access tokens"
    )


# ── The spine, stated directly ───────────────────────────────────────


def test_an_access_token_whose_session_row_is_gone_is_rejected(api_client, live_user, settings):
    """Fail closed: no live session row, no authentication.

    Deleting the row (rather than revoking it) stands in for every way a token
    can outlive its session — including a mint path that never registered one.
    """
    access, _ = _login(api_client, live_user, settings)
    assert _protected_read(api_client, access) == 200

    UserSession.objects.filter(user=live_user).delete()

    assert _protected_read(api_client, access) == 401


def test_the_websocket_handshake_honours_revocation(api_client, live_user, settings):
    """The Channels middleware shares the auth path, so it must share the check.

    Asserted through ``_resolve_user_from_token_sync``, which the middleware
    exposes precisely so tests can drive it without an event loop.
    """
    from django.contrib.auth.models import AnonymousUser

    from infrastructure.realtime.middleware import _resolve_user_from_token_sync

    access, refresh = _login(api_client, live_user, settings)
    assert not isinstance(_resolve_user_from_token_sync(access), AnonymousUser)

    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
    api_client.post(reverse("logout"), {"refresh": refresh}, format="json")

    assert isinstance(_resolve_user_from_token_sync(access), AnonymousUser), (
        "a logged-out token still opened a WebSocket"
    )


# ── Every mint must register a session, or it cannot be revoked ──────


def test_email_verification_sign_in_registers_a_revocable_session(api_client, user_factory, mailoutbox, settings):
    """`GET /identity/email-verify/` signs the user in. That session must exist.

    It minted a token carrying a ``sid`` but never wrote the ``UserSession`` row,
    so the resulting session was invisible to ``/identity/me/sessions/`` and
    could not be revoked by anything.
    """
    import re

    from components.identity.application.providers.identity_provider import IdentityProvider

    settings.SECURITY_EVENTS_ASYNC = False
    user = user_factory(password=PASSWORD)
    user.is_verified = False
    user.save(update_fields=["is_verified"])

    mailoutbox.clear()
    IdentityProvider.build_send_verification_email_use_case().execute(
        user_id=user.id,
        confirmation_base_url="https://example.test/confirm",
        site_name="Auto-Sec",
        site_domain="example.test",
    )
    token = re.search(r"token=([A-Za-z0-9._-]+)", mailoutbox[0].body).group(1)

    api_client.credentials()
    response = api_client.get(reverse("email-verify"), {"token": token})
    assert response.status_code == 200, response.data
    access = response.data["tokens"]["access"]

    assert UserSession.objects.filter(user=user).count() == 1, (
        "email verification signed the user in without registering a session — it cannot be revoked"
    )
    assert _protected_read(api_client, access) == 200
