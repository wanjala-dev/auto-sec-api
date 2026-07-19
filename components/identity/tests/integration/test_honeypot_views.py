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
