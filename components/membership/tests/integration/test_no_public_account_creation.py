"""``POST /membership/join/register/`` is gone, and must stay gone.

It created an account from an unauthenticated POST and signed the caller in.
Both halves were wrong, and both were invisible because the endpoint 500'd on
a fork-drift ``ImportError`` before reaching them::

    File "components/membership/api/join_controller.py", line 170, in post
        WorkspaceMembership = get_team_models_provider().WorkspaceMembership
    ImportError: cannot import name 'WorkspaceMembership' from
                 'infrastructure.persistence.team.models'

``WorkspaceMembership`` lives in ``infrastructure.persistence.workspaces.models``,
so repairing it was a one-line provider edit away. With the provider patched to
return the real model, the endpoint answered ``201`` and:

* wrote ``is_verified=True`` — an account that never proved inbox control, past
  the gate ``/identity/login/`` enforces;
* returned a token pair minted by a bare ``RefreshToken.for_user``, whose access
  claims were ``['exp', 'iat', 'jti', 'token_type', 'user_id']`` — **no ``sid``**
  — with ``0`` ``UserSession`` rows behind it, so the very next authenticated
  read came back ``401`` under the fail-closed rule #427 introduced.

It was also an undeclared second login: an existing account whose password
matched fell through to the same mint, with none of ``/identity/login/``'s 2FA
check, lockout, per-email + per-IP throttles, or login-activity trail.

The replacement is two endpoints that each already owned one half:
``POST /identity/register/`` creates the account, and
``POST /membership/join/relationship/`` attaches the authenticated user to a
workspace via ``EstablishWorkspaceRelationshipUseCase``.
"""

from __future__ import annotations

import pytest
from django.urls import NoReverseMatch, reverse

pytestmark = pytest.mark.django_db

JOIN_REGISTER_URL = "/api/v1/membership/join/register/"
QA_EMAIL = "public-join@qa.autosec.local"


class TestPublicJoinRegisterIsGone:
    def test_route_does_not_resolve(self, api_client, workspace_factory):
        workspace = workspace_factory()

        response = api_client.post(
            JOIN_REGISTER_URL,
            {
                "email": QA_EMAIL,
                "password": "Sup3rSecret!pass",
                "workspace_id": str(workspace.id),
            },
            format="json",
        )

        assert response.status_code == 404

    def test_route_name_is_unregistered(self):
        """A name left in the URLconf is a route waiting to be re-pointed."""
        with pytest.raises(NoReverseMatch):
            reverse("membership:join-register")

    def test_controller_symbol_is_gone(self):
        from components.membership.api import join_controller

        assert not hasattr(join_controller, "JoinRegisterController")

    def test_no_account_is_created_by_the_anonymous_post(self, api_client, workspace_factory):
        """The endpoint's whole purpose — creating an account without auth."""
        from infrastructure.persistence.users.models import CustomUser

        workspace = workspace_factory()
        api_client.post(
            JOIN_REGISTER_URL,
            {
                "email": QA_EMAIL,
                "password": "Sup3rSecret!pass",
                "workspace_id": str(workspace.id),
            },
            format="json",
        )

        assert not CustomUser.objects.filter(email=QA_EMAIL).exists()


class TestNoAnonymousEndpointMintsAPreVerifiedAccount:
    """The canonical account-creation path still makes people prove their inbox."""

    def test_identity_register_leaves_the_account_unverified(self, api_client):
        from infrastructure.persistence.users.models import CustomUser

        response = api_client.post(
            "/api/v1/identity/register/",
            {
                "email": QA_EMAIL,
                "username": "publicjoinqa",
                "password": "Sup3rSecret!pass",
            },
            format="json",
        )

        assert response.status_code == 200, response.data
        user = CustomUser.objects.get(email=QA_EMAIL)
        assert user.is_verified is False

    def test_identity_register_does_not_sign_the_caller_in(self, api_client):
        """No token in the body, and no session row — registration is not a login."""
        from infrastructure.persistence.users.models import CustomUser, UserSession

        response = api_client.post(
            "/api/v1/identity/register/",
            {
                "email": QA_EMAIL,
                "username": "publicjoinqa",
                "password": "Sup3rSecret!pass",
            },
            format="json",
        )

        assert response.status_code == 200, response.data
        body = str(response.data)
        assert "access" not in body and "refresh" not in body
        user = CustomUser.objects.get(email=QA_EMAIL)
        assert UserSession.objects.filter(user=user).count() == 0
