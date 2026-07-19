"""Unit tests for RegisterUserUseCase.

Specifically guards the brand-name boundary: the use case must forward the
distinct ``site_name`` (brand, e.g. "Octopus") to the email port — never the
``site_domain`` (API host, e.g. "api.wanjala.art"). Conflating the two was the
bug that produced the "Welcome to api.wanjala.art" subject line in production
welcome emails.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

from components.identity.application.commands.register_command import (
    RegisterCommand,
)
from components.identity.application.use_cases.register_user_use_case import (
    RegisterUserUseCase,
)


@dataclass
class _User:
    id: UUID
    email: str
    username: str


class _FakeUserRepo:
    def __init__(self, user: _User) -> None:
        self._user = user

    def create_user(self, *, username: str, email: str, password: str) -> _User:
        return self._user


@dataclass
class _TokenPair:
    access: str
    refresh: str | None = None


class _FakeTokenPort:
    def issue_tokens(self, user_id, *, otp_verified, device_id, include_refresh):
        return _TokenPair(access="access-token-abc")


class _RecordingEmailPort:
    def __init__(self) -> None:
        self.last_call: dict | None = None

    def send_verification_email(self, **kwargs) -> bool:
        self.last_call = kwargs
        return True


def _build_use_case(email_port=None):
    user = _User(id=uuid4(), email="user@example.com", username="user")
    return (
        RegisterUserUseCase(
            user_repo=_FakeUserRepo(user),
            token_port=_FakeTokenPort(),
            email_port=email_port or _RecordingEmailPort(),
        ),
        user,
    )


def test_register_forwards_brand_site_name_to_email_port_not_site_domain():
    email_port = _RecordingEmailPort()
    use_case, _user = _build_use_case(email_port=email_port)

    use_case.execute(
        RegisterCommand(
            username="user",
            email="user@example.com",
            password="hunter2",
            site_name="Octopus",
            site_domain="api.wanjala.art",
            confirmation_base_url="https://demo.octopusintl.org/EmailConfirmed/",
        )
    )

    assert email_port.last_call is not None
    assert email_port.last_call["site_name"] == "Octopus"
    assert email_port.last_call["site_domain"] == "api.wanjala.art"


def test_register_builds_verification_url_from_confirmation_base_and_access_token():
    email_port = _RecordingEmailPort()
    use_case, _ = _build_use_case(email_port=email_port)

    use_case.execute(
        RegisterCommand(
            username="user",
            email="user@example.com",
            password="hunter2",
            site_name="Octopus",
            site_domain="api.wanjala.art",
            confirmation_base_url="https://demo.octopusintl.org/EmailConfirmed/",
        )
    )

    assert (
        email_port.last_call["verification_url"]
        == "https://demo.octopusintl.org/EmailConfirmed/?token=access-token-abc"
    )


def test_register_returns_warning_when_email_dispatch_fails():
    class _FailingEmailPort(_RecordingEmailPort):
        def send_verification_email(self, **kwargs) -> bool:
            super().send_verification_email(**kwargs)
            return False

    use_case, _ = _build_use_case(email_port=_FailingEmailPort())
    result = use_case.execute(
        RegisterCommand(
            username="user",
            email="user@example.com",
            password="hunter2",
            site_name="Octopus",
            site_domain="api.wanjala.art",
            confirmation_base_url="https://demo.octopusintl.org/EmailConfirmed/",
        )
    )

    assert result.email_sent is False
    assert result.warning is not None
    assert "verification email" in result.warning.lower()
