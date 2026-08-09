"""Integration tests for the public resend-verification recovery path.

The verification gate (login refuses unverified users) is only honest if a
user who never received the email can ask for another one. These tests
drive the REAL endpoint end-to-end:

    register (unverified) → POST /identity/resend-verification/ →
    Celery task (eager) → email in the outbox → the RESENT token verifies.

Invariants under test:
  * always 202, byte-identical body for known / unknown / verified — the
    endpoint must not be an account-existence oracle;
  * only unverified accounts actually get an email;
  * the resend is audit-logged (auth.email_verification_resent);
  * the per-IP throttle caps anonymous flooding with 429.

Email delivery is queued post-commit, so the sending legs wrap the request
in ``django_capture_on_commit_callbacks(execute=True)`` — exactly how the
real request path behaves after COMMIT.
"""

from __future__ import annotations

import re

import pytest
from django.core import mail
from django.core.cache import cache

from infrastructure.persistence.users.models import AuthAuditEvent, CustomUser

REGISTER_URL = "/identity/register/"
RESEND_URL = "/identity/resend-verification/"
VERIFY_URL = "/identity/email-verify/"

_PASSWORD = "AutoSecResend2026!"
_NEUTRAL_DETAIL = "If an account exists for this address, a verification email has been sent."


def _token_from_email(message) -> str:
    match = re.search(r"token=([A-Za-z0-9._\-]+)", message.body)
    assert match, f"no verification token found in email body:\n{message.body}"
    return match.group(1)


@pytest.fixture(autouse=True)
def _clear_throttle_cache():
    """The DRF throttles count in the (process-wide) locmem cache — isolate tests."""
    cache.clear()
    yield
    cache.clear()


@pytest.mark.integration
@pytest.mark.django_db
class TestResendVerification:
    def _register(self, api_client, *, email, username):
        resp = api_client.post(
            REGISTER_URL,
            {"email": email, "username": username, "password": _PASSWORD},
            format="json",
        )
        assert resp.status_code == 200, resp.data
        return resp

    def test_unverified_account_gets_fresh_working_email(self, api_client, django_capture_on_commit_callbacks):
        email = "resend-me@acme-soc.example"
        self._register(api_client, email=email, username="resendme")
        mail.outbox.clear()

        with django_capture_on_commit_callbacks(execute=True):
            resp = api_client.post(RESEND_URL, {"email": email}, format="json")
        assert resp.status_code == 202, resp.data
        assert resp.data["detail"] == _NEUTRAL_DETAIL

        # The email actually went out (eager Celery), addressed correctly,
        # carrying the frontend confirm link.
        assert len(mail.outbox) == 1
        message = mail.outbox[0]
        assert email in message.to
        assert "/identity/email-confirmed" in message.body

        # The resend is audit-logged against the real user.
        user = CustomUser.objects.get(email=email)
        assert AuthAuditEvent.objects.filter(event_code="auth.email_verification_resent", user_id=user.id).exists()

        # And the RESENT token is genuinely usable — the full recovery loop.
        token = _token_from_email(message)
        resp = api_client.get(VERIFY_URL, {"token": token})
        assert resp.status_code == 200, resp.data
        user.refresh_from_db()
        assert user.is_verified is True

    def test_unknown_email_is_silent_202(self, api_client, django_capture_on_commit_callbacks):
        mail.outbox.clear()
        with django_capture_on_commit_callbacks(execute=True):
            resp = api_client.post(RESEND_URL, {"email": "ghost@acme-soc.example"}, format="json")
        assert resp.status_code == 202, resp.data
        assert resp.data["detail"] == _NEUTRAL_DETAIL
        assert mail.outbox == []
        assert not AuthAuditEvent.objects.filter(event_code="auth.email_verification_resent").exists()

    def test_verified_account_is_silent_202(self, api_client, django_capture_on_commit_callbacks):
        email = "already-verified@acme-soc.example"
        self._register(api_client, email=email, username="alreadyverified")
        CustomUser.objects.filter(email=email).update(is_verified=True)
        mail.outbox.clear()

        with django_capture_on_commit_callbacks(execute=True):
            resp = api_client.post(RESEND_URL, {"email": email}, format="json")
        assert resp.status_code == 202, resp.data
        assert resp.data["detail"] == _NEUTRAL_DETAIL
        assert mail.outbox == []

    def test_missing_email_is_400(self, api_client):
        resp = api_client.post(RESEND_URL, {}, format="json")
        assert resp.status_code == 400, resp.data

    def test_no_account_existence_oracle(self, api_client, django_capture_on_commit_callbacks):
        """Known-unverified vs unknown must be indistinguishable to the caller."""
        email = "oracle-probe@acme-soc.example"
        self._register(api_client, email=email, username="oracleprobe")

        with django_capture_on_commit_callbacks(execute=True):
            known = api_client.post(RESEND_URL, {"email": email}, format="json")
        with django_capture_on_commit_callbacks(execute=True):
            unknown = api_client.post(RESEND_URL, {"email": "nobody-here@acme-soc.example"}, format="json")

        assert known.status_code == unknown.status_code == 202
        assert known.data == unknown.data

    def test_per_ip_throttle_caps_flooding(self, api_client):
        """Rotating the email must not buy unlimited sends from one host."""
        cache.clear()
        responses = [
            api_client.post(
                RESEND_URL,
                {"email": f"flood-{i}@acme-soc.example"},
                format="json",
            )
            for i in range(11)
        ]
        assert all(r.status_code == 202 for r in responses[:10])
        assert responses[10].status_code == 429
