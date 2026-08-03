"""End-to-end API test for the user onboarding loop — the first flow Tom's org hits.

Drives the REAL endpoints in sequence, no mocks on the happy path:

    register  → user created, unverified, welcome email queued
    email-verify (with the token from that email) → is_verified flips True
    login     → succeeds, requires_org_onboarding=True (no org yet), tokens minted
    workspaces/create → the user's first workspace
    login     → requires_org_onboarding flips False

Plus the cheap edges: a login BEFORE verification is rejected (email_not_verified),
a duplicate register is rejected, and a bad verify token is rejected. These are the
onboarding invariants that were previously uncovered at the API layer.
"""

from __future__ import annotations

import re

import pytest
from django.core import mail

from infrastructure.persistence.users.models import CustomUser

REGISTER_URL = "/identity/register/"
VERIFY_URL = "/identity/email-verify/"
LOGIN_URL = "/identity/login/"
WORKSPACE_CREATE_URL = "/workspaces/create/"

_PASSWORD = "AutoSecOnboard2026!"


def _token_from_verification_email(message) -> str:
    """Pull the ``?token=<jwt>`` off the verification link in the welcome email body."""
    match = re.search(r"token=([A-Za-z0-9._\-]+)", message.body)
    assert match, f"no verification token found in email body:\n{message.body}"
    return match.group(1)


@pytest.mark.integration
@pytest.mark.django_db
class TestOnboardingFlow:
    def _register(self, api_client, *, email, username):
        return api_client.post(
            REGISTER_URL,
            {"email": email, "username": username, "password": _PASSWORD},
            format="json",
        )

    def test_full_onboarding_sequence(self, api_client):
        email = "founder@acme-soc.example"
        username = "acmefounder"

        # 1. Register — user is created, unverified, and a welcome email is queued.
        mail.outbox.clear()
        resp = self._register(api_client, email=email, username=username)
        assert resp.status_code == 200, resp.data
        assert resp.data["data"]["email"] == email

        user = CustomUser.objects.get(email=email)
        assert user.is_verified is False
        assert len(mail.outbox) == 1
        welcome = mail.outbox[0]
        assert email in welcome.to
        assert "Welcome" in welcome.subject

        # 2. Verify email with the REAL token carried in that email.
        token = _token_from_verification_email(welcome)
        resp = api_client.get(VERIFY_URL, {"token": token})
        assert resp.status_code == 200, resp.data
        assert resp.data["detail"] == "Successfully activated"
        user.refresh_from_db()
        assert user.is_verified is True

        # 3. Login — succeeds now, and the org-onboarding gate is OPEN (no workspace yet).
        resp = api_client.post(LOGIN_URL, {"email": email, "password": _PASSWORD}, format="json")
        assert resp.status_code == 200, resp.data
        assert resp.data["requires_org_onboarding"] is True
        assert resp.data["org_membership_count"] == 0
        assert resp.data["tokens"]["access"]
        access = resp.data["tokens"]["access"]

        # 4. Create the first workspace (authenticated with the freshly minted token).
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
        resp = api_client.post(WORKSPACE_CREATE_URL, {"workspace_name": "Acme SOC"}, format="json")
        assert resp.status_code == 201, resp.data
        assert resp.data["workspace_name"] == "Acme SOC"
        api_client.credentials()  # clear auth header for the anonymous login below

        # 5. Login again — the org-onboarding gate has CLOSED (they now own an org).
        resp = api_client.post(LOGIN_URL, {"email": email, "password": _PASSWORD}, format="json")
        assert resp.status_code == 200, resp.data
        assert resp.data["requires_org_onboarding"] is False
        assert resp.data["org_membership_count"] == 1

    def test_login_before_verification_is_rejected(self, api_client):
        email = "unverified@acme-soc.example"
        resp = self._register(api_client, email=email, username="unverifieduser")
        assert resp.status_code == 200, resp.data

        resp = api_client.post(LOGIN_URL, {"email": email, "password": _PASSWORD}, format="json")
        # The login use case fails with email_not_verified → AuthenticationFailed.
        assert resp.status_code in (401, 403), resp.data

    def test_duplicate_register_is_rejected(self, api_client):
        email = "dupe@acme-soc.example"
        first = self._register(api_client, email=email, username="dupeuser")
        assert first.status_code == 200, first.data

        second = self._register(api_client, email=email, username="dupeuser2")
        assert second.status_code == 400, second.data
        assert CustomUser.objects.filter(email=email).count() == 1

    def test_verify_with_invalid_token_is_rejected(self, api_client):
        resp = api_client.get(VERIFY_URL, {"token": "not-a-real-jwt"})
        assert resp.status_code == 400, resp.data
        assert "error" in resp.data

    def test_verify_without_token_is_rejected(self, api_client):
        resp = api_client.get(VERIFY_URL)
        assert resp.status_code == 400, resp.data
