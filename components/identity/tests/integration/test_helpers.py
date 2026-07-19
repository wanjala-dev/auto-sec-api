"""Unit tests for lightweight helper utilities in users."""

from types import SimpleNamespace

import pytest
from django.test import RequestFactory

from infrastructure.persistence.users import utils
from infrastructure.persistence.users import views
from infrastructure.persistence.users import security
from infrastructure.persistence.users.models import CustomUser


pytestmark = pytest.mark.django_db


def test_security_metadata_includes_ip_and_user_agent():
    rf = RequestFactory()
    request = rf.get(
        "/",
        HTTP_USER_AGENT="pytest-agent",
        REMOTE_ADDR="127.0.0.1",
    )

    metadata = views._security_metadata(request, extra={"foo": "bar"})

    assert metadata["ip"] == "127.0.0.1"
    assert metadata["user_agent"] == "pytest-agent"
    assert metadata["foo"] == "bar"


def test_get_system_actor_prefers_superuser(monkeypatch, db):
    monkeypatch.setattr(views, "_SYSTEM_ACTOR_CACHE", None, raising=False)
    CustomUser.objects.create_superuser(
        email="admin@example.com",
        username="admin",
        password="pass1234",
    )

    actor = views._get_system_actor()

    assert actor is not None
    assert actor.is_superuser


def test_notify_security_event_dispatches(monkeypatch, user_factory, settings):
    monkeypatch.setattr(views, "_SYSTEM_ACTOR_CACHE", None, raising=False)
    settings.SECURITY_EVENTS_ASYNC = False
    actor = CustomUser.objects.create_superuser(
        email="admin@example.com",
        username="admin",
        password="pass1234",
    )
    user = user_factory()
    rf = RequestFactory()
    request = rf.get("/", HTTP_USER_AGENT="pytest-agent", REMOTE_ADDR="10.0.0.1")
    called = {}

    def fake_dispatch(self, **kwargs):
        called["kwargs"] = kwargs

    monkeypatch.setattr(security.NotificationDispatcher, "dispatch", fake_dispatch)

    views._notify_security_event(
        user=user,
        verb="logged in",
        event_code="auth.login",
        request=request,
        actor=actor,
    )

    assert called["kwargs"]["actor"] == actor
    assert called["kwargs"]["recipients"] == [user]
    assert called["kwargs"]["metadata"]["event"] == "auth.login"
    assert called["kwargs"]["metadata"]["ip"] == "10.0.0.1"


def test_build_frontend_url(monkeypatch):
    request = RequestFactory().get("/")
    monkeypatch.setattr(views, "resolve_frontend_base_url", lambda **kwargs: "http://example.com")

    url = views._build_frontend_url(request, "path/to/resource", site_domain="example.com")

    assert url == "http://example.com/path/to/resource"


def test_jwt_otp_payload_includes_device(user_factory):
    user = user_factory()
    device = SimpleNamespace(persistent_id="device-1", user_id=user.id, confirmed=True)

    payload = utils.jwt_otp_payload(user, device)

    assert payload["user_id"] == user.id
    assert payload["otp_device_id"] == "device-1"


def test_jwt_otp_payload_excludes_unmatched_device(user_factory):
    user = user_factory()
    other_device = SimpleNamespace(persistent_id="device-2", user_id="someone-else", confirmed=True)

    payload = utils.jwt_otp_payload(user, other_device)

    assert payload["otp_device_id"] is None
