"""Coverage for login response mode variations."""

import pytest
from django.urls import reverse


pytestmark = pytest.mark.django_db


def test_login_minimal_response(api_client, user_factory, settings):
    settings.SECURITY_EVENTS_ASYNC = False
    user = user_factory(password="pass1234")
    user.is_verified = True
    user.save(update_fields=["is_verified"])

    response = api_client.post(
        f"{reverse('login')}?response=minimal",
        {"email": user.email, "password": "pass1234"},
        format="json",
    )

    assert response.status_code == 200
    assert response.data["user_id"] == str(user.id)
    assert response.data["requires_org_onboarding"] is True
    assert response.data["org_membership_count"] == 0
    assert "org_access_workspaces" not in response.data
    assert "tokens" in response.data


def test_login_minimal_includes_preauth_token_when_otp_required(api_client, user_factory, settings):
    settings.SECURITY_EVENTS_ASYNC = False
    user = user_factory(password="pass1234")
    user.is_verified = True
    user.two_factor_enabled = True
    user.save(update_fields=["is_verified", "two_factor_enabled"])

    from django_otp.plugins.otp_totp.models import TOTPDevice

    TOTPDevice.objects.create(user=user, confirmed=True)

    response = api_client.post(
        f"{reverse('login')}?response=minimal",
        {"email": user.email, "password": "pass1234"},
        format="json",
    )

    assert response.status_code == 200
    assert response.data["tokens"] == {}
    assert response.data["otp_required"] is True
    assert isinstance(response.data["preauth_token"], str)
    assert response.data["preauth_token"]
