"""Tests for the WebSocket JWT auth middleware.

The frontend opens `wss://...?token=<jwt>`, this middleware decodes
the token and attaches the user. Anonymous users get rejected by the
consumer's auth guard (separate test surface).
"""

from __future__ import annotations

import pytest
from django.contrib.auth.models import AnonymousUser

from infrastructure.persistence.users.models import CustomUser
from infrastructure.realtime.middleware import _resolve_user_from_token_sync


@pytest.mark.django_db
def test_invalid_token_returns_anonymous():
    user = _resolve_user_from_token_sync("not-a-real-jwt")
    assert isinstance(user, AnonymousUser)


@pytest.mark.django_db
def test_empty_token_returns_anonymous():
    user = _resolve_user_from_token_sync("")
    assert isinstance(user, AnonymousUser)


@pytest.mark.django_db
def test_valid_token_returns_real_user():
    user = CustomUser.objects.create_user(
        email="ws-jwt@example.com",
        username="ws-jwt@example.com",
        password="pass1234",
    )
    from rest_framework_simplejwt.tokens import AccessToken

    raw = str(AccessToken.for_user(user))
    resolved = _resolve_user_from_token_sync(raw)
    assert not isinstance(resolved, AnonymousUser)
    assert resolved.id == user.id
