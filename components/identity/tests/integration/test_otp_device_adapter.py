"""Regression coverage for DjangoOTPDeviceAdapter against REAL devices.

The stubbed OTP tests mock ``verify_token``, so they never exercised the
adapter itself — which queried the ABSTRACT ``django_otp.models.Device``
(no manager) and raised ``AttributeError: Manager isn't available; Device
is abstract``, 500-ing every OTP verification. These tests hit the concrete
TOTP/Static device classes end-to-end so that regression can't return.
"""

import pytest
from django_otp.oath import totp
from django_otp.plugins.otp_static.models import StaticDevice
from django_otp.plugins.otp_totp.models import TOTPDevice

from components.identity.infrastructure.adapters.otp_device_adapter import (
    DjangoOTPDeviceAdapter,
)
from infrastructure.persistence.users.models import CustomUser

pytestmark = pytest.mark.django_db


def _user(email: str) -> CustomUser:
    return CustomUser.objects.create_user(email=email, username=email, password="pass1234")


def test_verify_token_totp_uses_concrete_device():
    user = _user("otp-adapter-totp@test.local")
    device = TOTPDevice.objects.create(user=user, name="totp", confirmed=True)
    code = str(totp(device.bin_key, step=device.step, t0=device.t0, digits=device.digits)).zfill(device.digits)

    adapter = DjangoOTPDeviceAdapter()
    assert adapter.verify_token(device.id, code, method="totp") is True
    assert adapter.verify_token(device.id, "000000", method="totp") is False


def test_verify_token_static_uses_concrete_device():
    user = _user("otp-adapter-static@test.local")
    device = StaticDevice.objects.create(user=user, name="static", confirmed=True)
    device.token_set.create(token="RECOVER01")

    adapter = DjangoOTPDeviceAdapter()
    assert adapter.verify_token(device.id, "RECOVER01", method="static") is True


def test_verify_token_missing_device_returns_false():
    adapter = DjangoOTPDeviceAdapter()
    assert adapter.verify_token(999999, "123456", method="totp") is False


def test_issue_tokens_with_device_id_mints_real_tokens():
    """The OTP-success step of a 2FA login: after verification the token
    adapter resolves the device by id to stamp its persistent_id into the
    JWT. It used to do Device.objects.get on the ABSTRACT Device
    (AttributeError -> 500 as the very last step of login). Must resolve the
    concrete device and return real access + refresh tokens."""
    from components.identity.infrastructure.adapters.jwt_token_adapter import (
        JWTTokenAdapter,
    )

    user = _user("otp-issue-tokens@test.local")
    device = TOTPDevice.objects.create(user=user, name="totp", confirmed=True)

    pair = JWTTokenAdapter().issue_tokens(
        user.id, otp_verified=True, device_id=device.id, include_refresh=True
    )
    assert pair.access
    assert pair.refresh
