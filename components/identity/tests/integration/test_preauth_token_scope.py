"""The login pre-auth token must ONLY be able to complete an OTP challenge.

A 2FA login is a two-step mint: ``LoginUseCase`` withholds the real token pair
and hands back a short-lived pre-auth token; the real pair is minted by
``VerifyOTPUseCase`` once the OTP checks out.

That contract is only worth something if the pre-auth token is powerless
everywhere else. It used to be a plain ``AccessToken`` carrying an extra
``otp_pending`` claim that nothing consulted, so it authenticated every
``IsAuthenticated`` endpoint in the product — a complete 2FA bypass for anyone
holding just the password. These tests pin the contract from both sides:
rejected everywhere, accepted on the OTP-completion endpoints.
"""

import pytest
from django.urls import reverse
from django_otp.oath import totp
from django_otp.plugins.otp_totp.models import TOTPDevice

from components.identity.infrastructure.adapters import user_utils

pytestmark = pytest.mark.django_db


def _totp_code(device: TOTPDevice) -> str:
    return str(totp(device.bin_key, step=device.step, t0=device.t0, digits=device.digits)).zfill(device.digits)


@pytest.fixture
def two_factor_user(user_factory):
    """A verified user with 2FA armed on a confirmed TOTP device."""
    user = user_factory(password="pass1234")
    user.is_verified = True
    user.two_factor_enabled = True
    user.save(update_fields=["is_verified", "two_factor_enabled"])
    device = TOTPDevice.objects.create(user=user, confirmed=True)
    return user, device


def _login_for_preauth(api_client, user, settings) -> str:
    """Drive the real login endpoint and return the pre-auth token."""
    settings.SECURITY_EVENTS_ASYNC = False
    response = api_client.post(
        reverse("login"),
        {"email": user.email, "password": "pass1234"},
        format="json",
    )
    assert response.status_code == 200
    assert response.data["otp_required"] is True
    assert response.data["tokens"] == {}
    preauth = response.data["preauth_token"]
    assert isinstance(preauth, str) and preauth
    return preauth


# ── The bypass: the pre-auth token must not authenticate anything ────


@pytest.mark.parametrize(
    "url_name",
    ["user-summary", "notifications:notification-list"],
)
def test_preauth_token_is_rejected_by_authenticated_read_endpoints(api_client, two_factor_user, settings, url_name):
    """Never presenting the OTP must not buy read access to the product."""
    user, _device = two_factor_user
    preauth = _login_for_preauth(api_client, user, settings)

    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {preauth}")
    response = api_client.get(reverse(url_name))

    assert response.status_code == 401, (
        f"{url_name} accepted a pre-auth token — 2FA is bypassable with the password alone (got {response.status_code})"
    )


def test_preauth_token_is_rejected_by_authenticated_write_endpoint(api_client, two_factor_user, settings):
    """And it must certainly not buy WRITE access."""
    user, _device = two_factor_user
    original_first_name = user.first_name
    preauth = _login_for_preauth(api_client, user, settings)

    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {preauth}")
    response = api_client.patch(
        reverse("user-base-edit", kwargs={"uuid": str(user.id)}),
        {"first_name": "PreauthWrite"},
        format="json",
    )

    assert response.status_code == 401, (
        f"user-base-edit accepted a pre-auth token for a WRITE (got {response.status_code})"
    )
    user.refresh_from_db()
    assert user.first_name == original_first_name, "the pre-auth write landed in the DB"


def test_preauth_token_does_not_authenticate_a_websocket(two_factor_user):
    """The WS middleware authenticates off the same token — same bypass."""
    from django.contrib.auth.models import AnonymousUser

    from infrastructure.realtime.middleware import _resolve_user_from_token_sync

    user, _device = two_factor_user
    preauth = user_utils.issue_preauth_token(user)

    resolved = _resolve_user_from_token_sync(preauth)

    assert isinstance(resolved, AnonymousUser), "a pre-auth token opened an authenticated WebSocket"


# ── The contract it must keep: OTP completion still works ────────────


def test_preauth_token_still_completes_totp_verification(api_client, two_factor_user, settings):
    """The one thing the pre-auth token exists to do must keep working."""
    user, device = two_factor_user
    preauth = _login_for_preauth(api_client, user, settings)

    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {preauth}")
    response = api_client.post(
        reverse("totp-verify"),
        {"token": _totp_code(device)},
        format="json",
    )

    assert response.status_code == 200, response.data
    assert response.data["otp_verified"] is True
    assert response.data["tokens"]["access"]
    assert response.data["tokens"]["refresh"]


def test_preauth_token_still_completes_static_recovery_verification(api_client, two_factor_user, settings):
    """Recovery codes are the other OTP-completion path — same allowance."""
    from django_otp.plugins.otp_static.models import StaticDevice

    user, _device = two_factor_user
    static_device = StaticDevice.objects.create(user=user, name="Static")
    static_device.token_set.create(token="recovery1")

    preauth = _login_for_preauth(api_client, user, settings)

    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {preauth}")
    response = api_client.post(
        reverse("static-verify"),
        {"token": "recovery1"},
        format="json",
    )

    assert response.status_code == 200, response.data
    assert response.data["otp_verified"] is True


def test_the_token_minted_after_otp_verification_is_a_normal_access_token(api_client, two_factor_user, settings):
    """The post-OTP pair must be fully powered — otherwise 2FA users are locked out."""
    user, device = two_factor_user
    preauth = _login_for_preauth(api_client, user, settings)

    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {preauth}")
    verify = api_client.post(reverse("totp-verify"), {"token": _totp_code(device)}, format="json")
    assert verify.status_code == 200, verify.data

    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {verify.data['tokens']['access']}")
    response = api_client.get(reverse("user-summary"))

    assert response.status_code == 200


def test_access_token_still_verifies_a_new_device_on_the_same_endpoint(api_client, user_factory):
    """``otp/verify/`` doubles as first-time 2FA enrolment for a logged-in user."""
    user = user_factory()
    device = TOTPDevice.objects.create(user=user, confirmed=False)
    tokens = user_utils.issue_tokens(user, otp_verified=False, include_refresh=False)

    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
    response = api_client.post(
        reverse("totp-verify"),
        {"token": _totp_code(device)},
        format="json",
    )

    assert response.status_code == 200, response.data
    assert response.data["otp_verified"] is True
