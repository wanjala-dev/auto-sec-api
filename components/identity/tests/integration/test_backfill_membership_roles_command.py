"""Coverage for the backfill_membership_roles management command.

A WorkspaceMembership with the invalid ``role='sponsor'`` (sponsor is a
persona, not an RBAC role) must be coerced to ``role='viewer'`` while the
persona is left intact. Valid roles must be untouched, and --dry-run must
not write.
"""
from __future__ import annotations

import pytest
from django.core.management import call_command

from infrastructure.persistence.users.models import CustomUser, UserProfile
from infrastructure.persistence.workspaces.models import (
    Workspace,
    WorkspaceMembership,
)


pytestmark = [pytest.mark.django_db]


def _user(email):
    user = CustomUser.objects.create_user(
        email=email, username=email, password="pass1234"
    )
    UserProfile.objects.get_or_create(user=user)
    return user


def _workspace(owner, name="Org"):
    return Workspace.objects.create(
        workspace_name=name, workspace_owner=owner, status="active"
    )


def _membership(workspace, user, *, role, persona):
    return WorkspaceMembership.objects.create(
        workspace=workspace,
        user=user,
        role=role,
        persona=persona,
        status=WorkspaceMembership.Status.ACTIVE,
    )


class TestBackfillMembershipRoles:
    def test_coerces_sponsor_role_to_viewer_keeps_persona(self):
        owner = _user("owner@example.com")
        ws = _workspace(owner)
        drifted = _membership(ws, _user("sp@example.com"), role="sponsor", persona="sponsor")

        call_command("backfill_membership_roles", verbosity=0)

        drifted.refresh_from_db()
        assert drifted.role == "viewer"
        assert drifted.persona == "sponsor"  # persona untouched

    def test_leaves_valid_roles_untouched(self):
        owner = _user("owner2@example.com")
        ws = _workspace(owner)
        viewer = _membership(ws, _user("v@example.com"), role="viewer", persona="sponsor")
        member = _membership(ws, _user("m@example.com"), role="member", persona="contributor")

        call_command("backfill_membership_roles", verbosity=0)

        viewer.refresh_from_db()
        member.refresh_from_db()
        assert viewer.role == "viewer"
        assert member.role == "member"

    def test_dry_run_does_not_write(self):
        owner = _user("owner3@example.com")
        ws = _workspace(owner)
        drifted = _membership(ws, _user("sp3@example.com"), role="sponsor", persona="sponsor")

        call_command("backfill_membership_roles", "--dry-run", verbosity=0)

        drifted.refresh_from_db()
        assert drifted.role == "sponsor"  # unchanged in dry run
