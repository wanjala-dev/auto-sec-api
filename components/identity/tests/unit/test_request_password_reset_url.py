"""Regression: the password-reset email URL must be well-formed.

A trailing slash on the frontend base URL ("https://host/") used to
produce a double slash ("https://host//PasswordResetConfirm/...") that
broke SPA routing and 404'd the reset page. The use case must rstrip
the base so the link is clickable.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

from components.identity.application.commands.reset_password_command import (
    RequestPasswordResetCommand,
)
from components.identity.application.ports.password_reset_port import (
    PasswordResetTokenInfo,
)
from components.identity.application.use_cases.request_password_reset_use_case import (
    RequestPasswordResetUseCase,
)
from components.identity.domain.value_objects.auth_tokens import RequestContext


@dataclass
class _User:
    id: UUID
    email: str


class _FakeUserRepo:
    def __init__(self, user):
        self._user = user

    def find_by_email(self, email):
        return self._user


class _FakeResetPort:
    def __init__(self):
        self.sent_url = None

    def generate_reset_token(self, user_id):
        return PasswordResetTokenInfo(uidb64="UID123", token="tok-456")

    def send_reset_email(self, *, email, reset_url):
        self.sent_url = reset_url


class _NullAudit:
    def record_event(self, **kwargs):
        pass


class _NullNotification:
    def notify_security_event(self, **kwargs):
        pass


def _run(reset_base_url, redirect_url=""):
    user = _User(id=uuid4(), email="alice@example.com")
    reset_port = _FakeResetPort()
    use_case = RequestPasswordResetUseCase(
        user_repo=_FakeUserRepo(user),
        reset_port=reset_port,
        audit_port=_NullAudit(),
        notification_port=_NullNotification(),
    )
    use_case.execute(
        RequestPasswordResetCommand(
            email=user.email,
            reset_base_url=reset_base_url,
            redirect_url=redirect_url,
            context=RequestContext(ip_address="127.0.0.1", user_agent="t"),
        )
    )
    return reset_port.sent_url


_EXPECTED = (
    "https://demo.example.com/identity/password-reset-confirm/UID123/tok-456/"
)


def test_trailing_slash_base_does_not_double_slash():
    url = _run("https://demo.example.com/")
    assert url == _EXPECTED
    # No double slash anywhere in the path portion.
    assert "//identity" not in url


def test_base_without_trailing_slash_is_unaffected():
    url = _run("https://demo.example.com")
    assert url == _EXPECTED


def test_points_at_canonical_frontend_route():
    # The link must hit the real route, not the legacy /PasswordResetConfirm
    # path that only resolves via a client-side redirect.
    url = _run("https://demo.example.com/")
    assert "/identity/password-reset-confirm/" in url


def test_redirect_url_is_appended_as_query():
    url = _run(
        "https://demo.example.com/",
        redirect_url="https://demo.example.com/identity/password-reset-confirm/",
    )
    assert url.startswith(_EXPECTED)
    assert url.endswith(
        "?redirect_url=https://demo.example.com/identity/password-reset-confirm/"
    )
