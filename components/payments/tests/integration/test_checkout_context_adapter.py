"""Regression tests for CheckoutContextAdapter.resolve_checkout_context.

Guards the GTM-blocking 400: the adapter used to read
``profile.first_name``/``profile.last_name`` which do not exist on
``UserProfile`` (it has ``name``). The resulting ``AttributeError`` was
swallowed by an over-broad ``except`` and surfaced as
"Failed to resolve user context: 'UserProfile' object has no attribute
'first_name'", blocking every paid workspace subscription checkout.
"""
from __future__ import annotations

import uuid

import pytest

from components.payments.infrastructure.adapters.checkout_context_adapter import (
    CheckoutContextAdapter,
)
from infrastructure.persistence.users.models import CustomUser, UserProfile


@pytest.mark.django_db
class TestCheckoutContextAdapter:
    def _user(self, **kwargs):
        defaults = dict(
            username=f"u-{uuid.uuid4().hex[:10]}",
            email=f"{uuid.uuid4().hex[:10]}@example.com",
        )
        defaults.update(kwargs)
        # Creating the user auto-creates its UserProfile via the
        # DjangoUserProfileSignalBridge (post_save) — so tests update the
        # existing profile rather than creating a second one.
        return CustomUser.objects.create(**defaults)

    def test_resolves_name_from_profile(self):
        user = self._user()
        UserProfile.objects.update_or_create(
            user=user, defaults={"name": "Aisha Otieno"}
        )

        _, email, name = CheckoutContextAdapter().resolve_checkout_context(
            workspace=None, user_id=str(user.id)
        )

        assert email == user.email
        assert name == "Aisha Otieno"

    def test_falls_back_to_full_name_when_profile_name_blank(self):
        user = self._user(first_name="Daniel", last_name="Mwangi")
        # the auto-created profile has a blank name -> fall back to the
        # user's full name.
        _, _, name = CheckoutContextAdapter().resolve_checkout_context(
            workspace=None, user_id=str(user.id)
        )

        assert name == "Daniel Mwangi"

    def test_missing_profile_is_not_fatal(self):
        """Even if the profile row is absent (legacy data), checkout must
        not 400 — the old code raised 'User profile not found.'"""
        user = self._user(first_name="Grace", last_name="Akinyi")
        UserProfile.objects.filter(user=user).delete()

        _, email, name = CheckoutContextAdapter().resolve_checkout_context(
            workspace=None, user_id=str(user.id)
        )

        assert email == user.email
        assert name == "Grace Akinyi"

    def test_falls_back_to_username_when_no_names(self):
        user = self._user(first_name="", last_name="")
        # no profile, no first/last -> username
        _, _, name = CheckoutContextAdapter().resolve_checkout_context(
            workspace=None, user_id=str(user.id)
        )
        assert name == user.username

    def test_unknown_user_raises_clean_value_error(self):
        with pytest.raises(ValueError, match="User not found"):
            CheckoutContextAdapter().resolve_checkout_context(
                workspace=None, user_id=str(uuid.uuid4())
            )

    def test_no_user_id_returns_none_name(self):
        team, email, name = CheckoutContextAdapter().resolve_checkout_context(
            workspace=None, user_id=None
        )
        assert (team, email, name) == (None, None, None)
