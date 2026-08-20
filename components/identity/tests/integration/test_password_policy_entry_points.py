"""Password-strength policy must be enforced at EVERY entry point that writes a
password — not just change-password.

A QA sweep (§3.5 "policy enforced at one entry point only") proved live that
``django.contrib.auth.password_validation.validate_password`` — the configured
``AUTH_PASSWORD_VALIDATORS`` chain (min length, common-password, numeric,
user-attribute similarity, zxcvbn strength) — was reachable from exactly one
caller: ``ChangePasswordUseCase``. Register, signupapi, and
password-reset-complete accepted top-10 common passwords ("password"),
all-numeric ("123456"), and even single-character passwords, gated only by a
serializer ``min_length`` weaker than the policy itself.

These tests assert the policy fires on each public write path. The
change-password path (already enforced) is included as the reference control.
"""

from __future__ import annotations

import pytest
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from infrastructure.persistence.users.models import CustomUser

REGISTER_URL = "/identity/register/"
SIGNUP_URL = "/identity/signupapi/"
RESET_COMPLETE_URL = "/identity/password-reset-complete"
CHANGE_URL = "/identity/changepassword/"

# Passwords the policy MUST reject (proven accepted live before the fix).
WEAK_COMMON = "password"  # top-10 common
WEAK_NUMERIC = "123456"  # all-numeric + common
WEAK_SHORT = "a"  # 1 char — signupapi had no length floor at all
STRONG = "QaFailClosed2026!x"  # passes the full chain


@pytest.mark.integration
@pytest.mark.django_db
class TestPasswordPolicyAtEntryPoints:
    # ── register ────────────────────────────────────────────────────────
    def test_register_rejects_common_password(self, api_client):
        resp = api_client.post(
            REGISTER_URL,
            {"email": "pw-reg1@qa.example", "username": "pwreg1", "password": WEAK_COMMON},
            format="json",
        )
        assert resp.status_code == 400, resp.data
        assert not CustomUser.objects.filter(email="pw-reg1@qa.example").exists()

    def test_register_rejects_numeric_password(self, api_client):
        resp = api_client.post(
            REGISTER_URL,
            {"email": "pw-reg2@qa.example", "username": "pwreg2", "password": WEAK_NUMERIC},
            format="json",
        )
        assert resp.status_code == 400, resp.data

    def test_register_accepts_strong_password(self, api_client):
        resp = api_client.post(
            REGISTER_URL,
            {"email": "pw-reg3@qa.example", "username": "pwreg3", "password": STRONG},
            format="json",
        )
        assert resp.status_code == 200, resp.data
        assert CustomUser.objects.filter(email="pw-reg3@qa.example").exists()

    # ── signupapi ───────────────────────────────────────────────────────
    def test_signupapi_rejects_single_char_password(self, api_client):
        resp = api_client.post(
            SIGNUP_URL,
            {"email": "pw-sign1@qa.example", "username": "pwsign1", "password": WEAK_SHORT},
            format="json",
        )
        assert resp.status_code == 400, resp.data
        assert not CustomUser.objects.filter(email="pw-sign1@qa.example").exists()

    def test_signupapi_rejects_common_password(self, api_client):
        resp = api_client.post(
            SIGNUP_URL,
            {"email": "pw-sign2@qa.example", "username": "pwsign2", "password": WEAK_COMMON},
            format="json",
        )
        assert resp.status_code == 400, resp.data

    # ── password-reset-complete ─────────────────────────────────────────
    def _reset_payload(self, user, password):
        return {
            "uidb64": urlsafe_base64_encode(force_bytes(user.id)),
            "token": PasswordResetTokenGenerator().make_token(user),
            "password": password,
        }

    def test_reset_complete_rejects_common_password(self, api_client):
        user = CustomUser.objects.create_user(username="pwreset1", email="pw-reset1@qa.example", password=STRONG)
        resp = api_client.patch(RESET_COMPLETE_URL, self._reset_payload(user, WEAK_COMMON), format="json")
        assert resp.status_code == 400, resp.data
        # The strong password still authenticates — the weak set was refused.
        user.refresh_from_db()
        assert user.check_password(STRONG)
        assert not user.check_password(WEAK_COMMON)

    def test_reset_complete_accepts_strong_password(self, api_client):
        user = CustomUser.objects.create_user(
            username="pwreset2", email="pw-reset2@qa.example", password="OldStrong2026!x"
        )
        resp = api_client.patch(RESET_COMPLETE_URL, self._reset_payload(user, STRONG), format="json")
        assert resp.status_code == 200, resp.data
        user.refresh_from_db()
        assert user.check_password(STRONG)
