"""The admin honeypot decoy at /admin/.

The honeypot's job is to be INDISTINGUISHABLE from a real Django admin while
recording who probed it. Two things therefore matter and are asserted here:

  * it answers like a real admin — a failed login renders 200 with the standard
    "enter the correct username and password" message. Anything else (notably a
    500) fingerprints the decoy instantly to any scanner;
  * the IP it attributes the attempt to is the one OUR gateway saw, not one the
    prober supplied. Otherwise the scanner we are trying to identify gets to
    dictate what we record about it.
"""

import pytest
from django.urls import reverse

from infrastructure.persistence.honeypot.models import HoneypotAttempt


@pytest.mark.django_db
class TestHoneypotView:
    """Capture interactions with the admin honeypot endpoint."""

    def test_get_renders_login(self, client):
        url = reverse("admin_honeypot:login")
        response = client.get(url)
        assert response.status_code == 200
        assert b"Log in" in response.content

    def test_post_records_attempt(self, client):
        url = reverse("admin_honeypot:login")
        response = client.post(
            url,
            {"username": "admin", "password": "secret"},
            HTTP_USER_AGENT="test-agent",
            REMOTE_ADDR="203.0.113.1",
        )

        assert response.status_code == 200
        attempt = HoneypotAttempt.objects.get()
        assert attempt.username == "admin"
        assert attempt.password == "secret"
        assert attempt.ip_address == "203.0.113.1"
        assert attempt.user_agent == "test-agent"
        assert attempt.path == url
        assert attempt.method == "POST"

    def test_failed_login_looks_like_a_real_admin(self, client):
        """Regression guard for the honeypot 500.

        `HoneypotLoginView._record_attempt` called `messages.error(...)` while
        `django.contrib.messages` was never imported, so every POST raised
        NameError and returned a 500 instead of the decoy. A real Django admin
        returns 200 and re-renders the form with an error — a 500 is a tell.
        """
        url = reverse("admin_honeypot:login")
        response = client.post(url, {"username": "root", "password": "toor"})

        assert response.status_code == 200
        assert b"correct username and password" in response.content
        # The decoy must never actually authenticate anyone.
        assert not response.wsgi_request.user.is_authenticated

    def test_recorded_ip_is_not_prober_supplied(self, client):
        """A forged X-Forwarded-For prefix must not become the attributed origin.

        With NUM_PROXIES=1 the trusted hop is the rightmost one — what our own
        gateway appended. `198.51.100.9` below is what the prober claimed.
        """
        url = reverse("admin_honeypot:login")
        client.post(
            url,
            {"username": "admin", "password": "secret"},
            HTTP_X_FORWARDED_FOR="198.51.100.9, 203.0.113.42",
            REMOTE_ADDR="10.0.0.1",
        )

        attempt = HoneypotAttempt.objects.get()
        assert attempt.ip_address == "203.0.113.42"
        assert attempt.ip_address != "198.51.100.9", "the prober chose its own attributed IP"
