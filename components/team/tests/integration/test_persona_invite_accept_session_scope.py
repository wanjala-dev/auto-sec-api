"""Accepting an invite must not hand out a session on someone else's account.

``POST /membership/invitations/persona/accept/`` is deliberately
unauthenticated — "the token IS the credential" — and returns a JWT pair so the
invitee lands signed in. That is sound for a brand-new account: the accept IS
the signup, and the person set the password in the same request.

It was NOT sound for an **established** account. Holding the invite token proves
nothing about being that user — and the inviter holds it too: the create
response returns the raw token in its body. So any workspace owner or admin
could invite an existing user's email address, read the token out of their own
201, POST it here, and receive a full 10-day ``access`` + ``refresh`` pair **as
that user**. Reproduced live: the resulting token answered
``/identity/me/summary/`` with the invitee's identity, performed writes, and
opened the notifications WebSocket.

The account it was minted for had TOTP armed and its password login correctly
answered ``otp_required: true`` — so this also walked past the second factor,
past the email-verification gate, and past account lockout. The token carried no
``sid`` claim either, so the session never appeared in
``/identity/me/sessions/`` and could not be revoked.

An invite grants MEMBERSHIP. Authentication is the login endpoint's job, where
2FA, verification and lockout all apply.
"""

from __future__ import annotations

import pytest
from django.urls import reverse
from django_otp.plugins.otp_totp.models import TOTPDevice
from rest_framework.test import APIClient

from infrastructure.persistence.users.models import CustomUser, UserProfile
from infrastructure.persistence.workspaces.models import Workspace, WorkspaceMembership

pytestmark = pytest.mark.django_db


def _user(email: str, *, password: str | None = None) -> CustomUser:
    user = CustomUser.objects.create_user(email=email, username=email, password=password)
    UserProfile.objects.get_or_create(user=user)
    return user


def _workspace(owner: CustomUser) -> Workspace:
    workspace = Workspace.objects.create(
        workspace_name="Invite Scope Org",
        workspace_owner=owner,
        status="active",
    )
    WorkspaceMembership.objects.create(
        workspace=workspace,
        user=owner,
        persona="admin",
        role=WorkspaceMembership.Role.OWNER,
        status=WorkspaceMembership.Status.ACTIVE,
    )
    return workspace


def _invite(owner: CustomUser, workspace: Workspace, email: str) -> str:
    """Create an invite as the owner and return the raw token it hands back."""
    client = APIClient()
    client.force_authenticate(user=owner)
    response = client.post(
        reverse("membership:membership-persona-invite"),
        {"workspace_id": str(workspace.id), "email": email, "persona": "auditor"},
        format="json",
    )
    assert response.status_code == 201, response.data
    return response.data["token"]


def _accept(token: str, **extra):
    return APIClient().post(
        reverse("membership:membership-persona-invite-accept"),
        {"token": token, **extra},
        format="json",
    )


# ── The takeover ─────────────────────────────────────────────────────


def test_accepting_an_invite_for_an_established_user_issues_no_session():
    """The inviter holds this token. It must not buy a session as the invitee."""
    owner = _user("owner-scope@example.com", password="ownerpass1")
    victim = _user("victim-scope@example.com", password="victimpass1")
    workspace = _workspace(owner)

    response = _accept(_invite(owner, workspace, victim.email))

    assert response.status_code == 200, response.data
    assert not response.data.get("access"), (
        "invite-accept handed out an access token for an established account — anyone who can "
        "create an invite can mint a session as that user"
    )
    assert not response.data.get("refresh")


def test_the_membership_still_lands_for_an_established_user():
    """Withholding the session must not break what the invite is FOR."""
    owner = _user("owner-mem@example.com", password="ownerpass1")
    invitee = _user("invitee-mem@example.com", password="inviteepass1")
    workspace = _workspace(owner)

    response = _accept(_invite(owner, workspace, invitee.email))

    assert response.status_code == 200, response.data
    assert WorkspaceMembership.objects.filter(
        workspace=workspace,
        user=invitee,
        status=WorkspaceMembership.Status.ACTIVE,
    ).exists()
    assert response.data.get("requires_login") is True, (
        "the frontend needs to know to route the invitee to the login screen"
    )


def test_invite_accept_does_not_bypass_a_second_factor():
    """The sharpest edge: the victim's own password login demands a second factor."""
    owner = _user("owner-2fa@example.com", password="ownerpass1")
    victim = _user("victim-2fa@example.com", password="victimpass1")
    victim.is_verified = True
    victim.two_factor_enabled = True
    victim.save(update_fields=["is_verified", "two_factor_enabled"])
    TOTPDevice.objects.create(user=victim, confirmed=True)
    workspace = _workspace(owner)

    response = _accept(_invite(owner, workspace, victim.email))

    assert response.status_code == 200, response.data
    assert not response.data.get("access"), (
        "invite-accept minted a session for a TOTP-armed account without the second factor"
    )


def test_the_issued_token_cannot_read_the_invitee_account(api_client):
    """Pin the consequence, not just the field: no token, no read."""
    owner = _user("owner-read@example.com", password="ownerpass1")
    victim = _user("victim-read@example.com", password="victimpass1")
    workspace = _workspace(owner)

    access = _accept(_invite(owner, workspace, victim.email)).data.get("access")

    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {access or 'none'}")
    response = api_client.get(reverse("user-summary"))

    assert response.status_code == 401, (
        f"a token from invite-accept read the invitee's account (got {response.status_code})"
    )


# ── The signup case, which is legitimate ─────────────────────────────


def test_a_brand_new_invitee_still_gets_signed_in():
    """For a new account the accept IS the signup — the password is set here.

    Withholding the session there would be a regression in the flow, not a fix.
    """
    owner = _user("owner-new-scope@example.com", password="ownerpass1")
    workspace = _workspace(owner)

    response = _accept(_invite(owner, workspace, "brand-new@example.com"), password="newuserpass1")

    assert response.status_code == 200, response.data
    assert response.data.get("access"), "a brand-new invitee was not signed in by their own signup"
    assert response.data.get("refresh")


def test_a_brand_new_invitee_s_token_actually_works(api_client):
    """Returning a token is not the same as being signed in.

    This asserted only that `access` was non-empty, which a token nothing
    accepts would also satisfy. Now that authentication checks the session
    registry, a mint that skips the registry produces exactly that: a
    well-formed token that authenticates nothing.
    """
    from django.urls import reverse as _reverse

    owner = _user("owner-works@example.com", password="ownerpass1")
    workspace = _workspace(owner)

    access = _accept(_invite(owner, workspace, "works-new@example.com"), password="newuserpass1").data["access"]

    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
    assert api_client.get(_reverse("user-summary")).status_code == 200, (
        "the token handed to a brand-new invitee does not authenticate"
    )


def test_a_brand_new_invitee_s_session_is_listed_and_revocable():
    """Their session must be visible in the registry like any other login.

    The invite path minted with a bare ``RefreshToken.for_user``, which stamps
    no ``sid`` and writes no ``UserSession`` row — an immortal session, absent
    from /identity/me/sessions/ and beyond the reach of revoke-others, password
    change and password reset.
    """
    from infrastructure.persistence.users.models import CustomUser, UserSession

    owner = _user("owner-listed@example.com", password="ownerpass1")
    workspace = _workspace(owner)

    _accept(_invite(owner, workspace, "listed-new@example.com"), password="newuserpass1")

    invitee = CustomUser.objects.get(email="listed-new@example.com")
    assert UserSession.objects.filter(user=invitee).count() == 1, (
        "invite-accept signed a new user in without registering a revocable session"
    )
