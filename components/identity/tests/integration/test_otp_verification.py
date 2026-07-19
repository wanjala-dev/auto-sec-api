"""Regression coverage for OTP enforcement helpers."""

import pytest
from django.test import RequestFactory

from components.identity.infrastructure.adapters import user_utils as utils


pytestmark = pytest.mark.django_db


def _auth_request(user, token: str):
    request = RequestFactory().get("/", HTTP_AUTHORIZATION=f"Bearer {token}")
    request.user = user
    return request


def test_otp_is_verified_returns_false_for_preauth_token(user_factory):
    """Pre-auth tokens are valid for login completion, but not OTP-gated views."""
    user = user_factory()
    user.two_factor_enabled = True
    user.save(update_fields=["two_factor_enabled"])
    token = utils.issue_preauth_token(user)

    assert utils.otp_is_verified(None, _auth_request(user, token)) is False


def test_otp_is_verified_returns_true_for_verified_totp_token(user_factory):
    user = user_factory()
    user.two_factor_enabled = True
    user.save(update_fields=["two_factor_enabled"])
    device = user.totpdevice_set.create(confirmed=True)
    tokens = utils.issue_tokens(user, otp_verified=True, device=device, include_refresh=False)

    assert utils.otp_is_verified(None, _auth_request(user, tokens["access"])) is True


def test_otp_is_verified_requires_jwt_device_to_exist(user_factory):
    """A verified JWT should not satisfy OTP if its recorded device was deleted."""
    user = user_factory()
    user.two_factor_enabled = True
    user.save(update_fields=["two_factor_enabled"])
    stale_device = user.totpdevice_set.create(confirmed=True)
    active_device = user.totpdevice_set.create(confirmed=True)
    tokens = utils.issue_tokens(user, otp_verified=True, device=stale_device, include_refresh=False)

    stale_device.delete()
    assert active_device.pk is not None

    assert utils.otp_is_verified(None, _auth_request(user, tokens["access"])) is False
