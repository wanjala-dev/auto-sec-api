"""Integration tests — the pending-invitation read must not leak magic-link tokens.

``GET /membership/invitations/pending/`` (and its twin ``GET
/membership/invitations/``) surface each pending invitation's LIVE magic-link
``token`` so an admin can copy the accept URL when email delivery fails. The
token IS the credential for ``POST /membership/invitations/persona/accept/``,
an ``AllowAny`` endpoint — whoever holds it becomes the member the invitation
describes, at the role the invitation carries.

The read was gated on "any active member of the workspace", so a read-only
VIEWER could list every pending invite, harvest a pending ADMIN invite's token,
accept it, and land an ``admin`` WorkspaceMembership — a full privilege
escalation from the lowest role in the product.

These tests pin the gate to the capability that already governs every other
member-administration action (``manage_users``: role change, member removal,
invite create/resend/cancel), and prove the admin copy-link path still works.
"""

from __future__ import annotations

import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db

LIVE_TOKEN = "090f1fc4747b09d8abe14b68f771afffb808f01909bc2b0f3f0426eb025a804e"


def _make_membership(workspace, user, *, role_slug):
    from infrastructure.persistence.workspaces.models import WorkspaceMembership, WorkspaceRole

    role_obj = WorkspaceRole.objects.get(workspace__isnull=True, slug=role_slug)
    return WorkspaceMembership.objects.create(
        workspace=workspace,
        user=user,
        role=role_slug,
        workspace_role=role_obj,
        persona="contributor",
        status=WorkspaceMembership.Status.ACTIVE,
    )


def _make_pending_admin_invite(workspace, *, invited_by=None):
    from infrastructure.persistence.team.models import Invitation

    return Invitation.objects.create(
        workspace=workspace,
        email="qa-admin-target@example.com",
        token=LIVE_TOKEN,
        persona="admin",
        role="admin",
        status=Invitation.INVITED,
        invited_by=invited_by,
    )


def _pending_url(workspace):
    return f"{reverse('membership:membership-pending-invitations')}?workspace_id={workspace.id}"


def _invitations_url(workspace):
    return f"{reverse('membership:membership-invite')}?workspace_id={workspace.id}"


def _tokens_in(response) -> list[str]:
    tokens = []
    for row in response.data.get("results") or []:
        for team in row.get("teams") or []:
            token = team.get("token")
            if token:
                tokens.append(token)
    return tokens


class TestPendingInvitationDeny:
    """Nobody without ``manage_users`` may read the pending-invite list."""

    @pytest.mark.parametrize("role_slug", ["viewer", "member"])
    @pytest.mark.parametrize("url_builder", [_pending_url, _invitations_url])
    def test_non_admin_member_cannot_read_pending_invitations(
        self, api_client, workspace_factory, user_factory, role_slug, url_builder
    ):
        owner = user_factory()
        actor = user_factory()
        workspace = workspace_factory(owner=owner)
        _make_membership(workspace, actor, role_slug=role_slug)
        _make_pending_admin_invite(workspace, invited_by=owner)

        api_client.force_authenticate(user=actor)
        response = api_client.get(url_builder(workspace))

        assert response.status_code == 403, response.data
        # The live magic-link token must not appear anywhere in the payload —
        # holding it is equivalent to holding the admin membership it grants.
        assert LIVE_TOKEN not in response.content.decode()

    def test_non_member_is_still_denied(self, api_client, workspace_factory, user_factory):
        owner = user_factory()
        outsider = user_factory()
        workspace = workspace_factory(owner=owner)
        _make_pending_admin_invite(workspace, invited_by=owner)

        api_client.force_authenticate(user=outsider)
        response = api_client.get(_pending_url(workspace))

        assert response.status_code == 403, response.data
        assert LIVE_TOKEN not in response.content.decode()


class TestPendingInvitationAllow:
    """The admin copy-link surface keeps working — that's why the token is served."""

    def test_owner_sees_the_invite_token(self, api_client, workspace_factory, user_factory):
        owner = user_factory()
        workspace = workspace_factory(owner=owner)
        _make_pending_admin_invite(workspace, invited_by=owner)

        api_client.force_authenticate(user=owner)
        response = api_client.get(_pending_url(workspace))

        assert response.status_code == 200, response.data
        assert response.data["count"] == 1
        assert LIVE_TOKEN in _tokens_in(response)

    def test_admin_sees_the_invite_token(self, api_client, workspace_factory, user_factory):
        owner = user_factory()
        admin = user_factory()
        workspace = workspace_factory(owner=owner)
        _make_membership(workspace, admin, role_slug="admin")
        _make_pending_admin_invite(workspace, invited_by=owner)

        api_client.force_authenticate(user=admin)
        response = api_client.get(_pending_url(workspace))

        assert response.status_code == 200, response.data
        assert LIVE_TOKEN in _tokens_in(response)

    def test_direct_manage_users_grant_is_honoured(self, api_client, workspace_factory, user_factory):
        """A member explicitly granted ``manage_users`` may already reassign
        roles and remove people, so the invite list is within their authority.
        The gate resolves grants, not just the legacy role string."""
        from infrastructure.persistence.workspaces.models import WorkspacePermissionGrant

        owner = user_factory()
        analyst = user_factory()
        workspace = workspace_factory(owner=owner)
        _make_membership(workspace, analyst, role_slug="member")
        WorkspacePermissionGrant.objects.create(
            workspace=workspace,
            user=analyst,
            permission_key="manage_users",
        )
        _make_pending_admin_invite(workspace, invited_by=owner)

        api_client.force_authenticate(user=analyst)
        response = api_client.get(_pending_url(workspace))

        assert response.status_code == 200, response.data
        assert LIVE_TOKEN in _tokens_in(response)
