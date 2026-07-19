"""Logout endpoint contract: idempotent, never blocks the user.

The logout API is a declaration of intent. A missing, expired, malformed,
or unrecognized refresh token MUST NOT prevent the response from being
204 — otherwise users on stale or corrupted sessions get trapped on the
"Logging out…" spinner indefinitely (the production failure mode that
prompted this hardening).
"""
import pytest
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from infrastructure.persistence.users.models import CustomUser


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture(autouse=True)
def disable_security_events_async(settings):
    settings.SECURITY_EVENTS_ASYNC = False


def _make_user(email: str = 'logout-contract@example.com') -> CustomUser:
    user = CustomUser.objects.create_user(
        email=email,
        username=email.split('@')[0],
        password='password123',
    )
    user.is_verified = True
    user.save(update_fields=['is_verified'])
    return user


@pytest.mark.django_db
def test_logout_unauthenticated_with_no_body_returns_204(api_client):
    """Anonymous client posts an empty body → still 204."""
    response = api_client.post(reverse('logout'), {}, format='json')
    assert response.status_code == 204
    assert response.get('X-Token-Revoked') == '0'


@pytest.mark.django_db
def test_logout_with_garbage_refresh_token_returns_204(api_client):
    """Malformed token → server skips blacklist, still 204."""
    response = api_client.post(
        reverse('logout'),
        {'refresh': 'not-a-real-jwt'},
        format='json',
    )
    assert response.status_code == 204
    assert response.get('X-Token-Revoked') == '0'


@pytest.mark.django_db
def test_logout_with_blank_refresh_returns_204(api_client):
    """Empty-string refresh field → still 204."""
    response = api_client.post(
        reverse('logout'),
        {'refresh': ''},
        format='json',
    )
    assert response.status_code == 204
    assert response.get('X-Token-Revoked') == '0'


@pytest.mark.django_db
def test_logout_with_already_blacklisted_token_returns_204(api_client):
    """Idempotent: re-submitting an already-blacklisted token does not 400."""
    user = _make_user()
    refresh = RefreshToken.for_user(user)
    refresh.blacklist()  # already blacklisted before the request

    api_client.force_authenticate(user=user)
    response = api_client.post(
        reverse('logout'),
        {'refresh': str(refresh)},
        format='json',
    )
    assert response.status_code == 204


@pytest.mark.django_db
def test_logout_with_valid_token_returns_204(api_client):
    """Happy path: a fresh refresh token is accepted and 204 returned."""
    user = _make_user(email='valid-token@example.com')
    refresh = RefreshToken.for_user(user)
    api_client.force_authenticate(user=user)

    response = api_client.post(
        reverse('logout'),
        {'refresh': str(refresh)},
        format='json',
    )
    assert response.status_code == 204
    assert response.get('X-Token-Revoked') == '1'


@pytest.mark.django_db
def test_logout_authenticated_with_no_refresh_token_returns_204(api_client):
    """Authenticated user without a refresh token (e.g. stale session) → 204."""
    user = _make_user(email='no-refresh@example.com')
    api_client.force_authenticate(user=user)

    response = api_client.post(reverse('logout'), {}, format='json')
    assert response.status_code == 204
