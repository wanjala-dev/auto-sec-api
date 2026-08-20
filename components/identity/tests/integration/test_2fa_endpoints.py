"""Coverage for 2FA/OTP endpoints behavior expected by the frontend."""

import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db

# These tests used to mint a bare token (``user.tokens()`` /
# ``issue_tokens(include_refresh=False)``) and set the header by hand. Neither
# registers a ``UserSession``, and the second stamps no ``sid`` at all, so
# neither is a credential the product would ever issue — and authentication now
# checks the registry. The shared ``authenticate_as`` fixture signs the user in
# the way login does.


def test_totp_create_returns_otpauth_url(api_client, user_factory, authenticate_as):
    user = user_factory()
    authenticate_as(api_client, user)

    response = api_client.get(reverse("totp-create"))

    assert response.status_code == 200
    assert "otpauth_url" in response.data


def test_static_create_requires_post(api_client, user_factory, authenticate_as):
    user = user_factory()
    device = user.totpdevice_set.create(confirmed=True)
    user.two_factor_enabled = True
    user.save(update_fields=["two_factor_enabled"])
    authenticate_as(api_client, user, otp_verified=True, device=device)

    response = api_client.get(reverse("static-create"))

    assert response.status_code == 405


def test_static_create_requires_password_and_verified_2fa(api_client, user_factory, authenticate_as):
    password = "pass1234"
    user = user_factory(password=password)
    device = user.totpdevice_set.create(confirmed=True)
    user.two_factor_enabled = True
    user.save(update_fields=["two_factor_enabled"])
    authenticate_as(api_client, user, otp_verified=True, device=device)

    response = api_client.post(reverse("static-create"), data={"password": password}, format="json")

    assert response.status_code == 201
    assert len(response.data["recovery_codes"]) == 6


def test_static_create_rejects_when_2fa_disabled(api_client, user_factory, authenticate_as):
    password = "pass1234"
    user = user_factory(password=password)
    device = user.totpdevice_set.create(confirmed=True)
    authenticate_as(api_client, user, otp_verified=True, device=device)

    response = api_client.post(reverse("static-create"), data={"password": password}, format="json")

    assert response.status_code == 403


def test_totp_delete_requires_password(api_client, user_factory, authenticate_as):
    password = "pass1234"
    user = user_factory(password=password)
    device = user.totpdevice_set.create(confirmed=True)
    user.two_factor_enabled = True
    user.save(update_fields=["two_factor_enabled"])
    authenticate_as(api_client, user, otp_verified=True, device=device)

    response = api_client.post(reverse("totp-delete"), data={}, format="json")

    assert response.status_code == 400


def test_totp_delete_disables_two_factor_and_deletes_devices(api_client, user_factory, authenticate_as):
    password = "pass1234"
    user = user_factory(password=password)
    unconfirmed = user.totpdevice_set.create(confirmed=False)
    confirmed = user.totpdevice_set.create(confirmed=True)
    user.two_factor_enabled = True
    user.save(update_fields=["two_factor_enabled"])
    authenticate_as(api_client, user, otp_verified=True, device=confirmed)

    response = api_client.post(reverse("totp-delete"), data={"password": password}, format="json")

    assert response.status_code == 200
    assert response.data["two_factor_enabled"] is False
    assert user.totpdevice_set.filter(pk=unconfirmed.pk).exists() is False
    assert user.totpdevice_set.filter(pk=confirmed.pk).exists() is False
