"""Integration tests — DELETE /workspaces/<ws>/members/<user_id>/ (task #114).

Covers the full rule set of member removal:

- ALLOW: an admin carrying ``manage_users`` revokes a member; the membership is
  SOFT-revoked (status → suspended, row retained), audited, and the removed
  user is notified.
- DENY: a viewer/member without ``manage_users`` gets 403; the owner can never
  be removed (400) — not even by themselves.
- LEAVE: any member may remove THEMSELVES without ``manage_users``.
- Idempotency: a second removal is a success no-op (``removed=false``), with no
  duplicate audit row and no second notification.
- 404 for a user who is not a member (existence never leaks through the gate).
"""

from __future__ import annotations

import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db


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


def _remove_url(workspace, user):
    return reverse(
        "workspace-member-remove",
        kwargs={"workspace_id": str(workspace.id), "user_id": str(user.id)},
    )


def _status_of(workspace, user) -> str:
    from infrastructure.persistence.workspaces.models import WorkspaceMembership

    return WorkspaceMembership.objects.get(workspace=workspace, user=user).status


class TestRemoveMemberAllow:
    def test_admin_removes_member_soft_revokes_row(self, api_client, workspace_factory, user_factory):
        from infrastructure.persistence.workspaces.models import WorkspaceMembership

        owner = user_factory()
        admin = user_factory()
        target = user_factory()
        workspace = workspace_factory(owner=owner)
        _make_membership(workspace, admin, role_slug="admin")
        _make_membership(workspace, target, role_slug="member")

        api_client.force_authenticate(user=admin)
        response = api_client.delete(_remove_url(workspace, target))

        assert response.status_code == 200, response.data
        assert response.data["removed"] is True
        assert response.data["already_revoked"] is False
        # SOFT revoke — the row is retained in the revoked state, never deleted.
        assert _status_of(workspace, target) == WorkspaceMembership.Status.SUSPENDED
        assert WorkspaceMembership.objects.filter(workspace=workspace, user=target).exists()

    def test_owner_can_remove_a_member(self, api_client, workspace_factory, user_factory):
        from infrastructure.persistence.workspaces.models import WorkspaceMembership

        owner = user_factory()
        target = user_factory()
        workspace = workspace_factory(owner=owner)
        _make_membership(workspace, target, role_slug="member")

        api_client.force_authenticate(user=owner)
        response = api_client.delete(_remove_url(workspace, target))

        assert response.status_code == 200, response.data
        assert _status_of(workspace, target) == WorkspaceMembership.Status.SUSPENDED

    def test_removal_is_audited(self, api_client, workspace_factory, user_factory):
        from infrastructure.persistence.audit.models import EntityAuditLog

        owner = user_factory()
        target = user_factory()
        workspace = workspace_factory(owner=owner)
        _make_membership(workspace, target, role_slug="member")

        api_client.force_authenticate(user=owner)
        api_client.delete(_remove_url(workspace, target))

        entries = EntityAuditLog.objects.filter(field_name="status")
        assert entries.exists(), "member removal must leave an audit trail"

    def test_removed_user_is_notified(
        self, api_client, workspace_factory, user_factory, django_capture_on_commit_callbacks
    ):
        """The dispatch funnel enqueues post-commit (tasks run eager in test
        settings), so the callbacks must be executed to observe the row."""
        from infrastructure.persistence.notifications.models import Notification

        owner = user_factory()
        target = user_factory()
        workspace = workspace_factory(owner=owner)
        _make_membership(workspace, target, role_slug="member")

        api_client.force_authenticate(user=owner)
        with django_capture_on_commit_callbacks(execute=True):
            api_client.delete(_remove_url(workspace, target))

        assert Notification.objects.filter(recipient=target).exists()


class TestRemoveMemberDeny:
    def test_member_without_manage_users_is_denied(self, api_client, workspace_factory, user_factory):
        from infrastructure.persistence.workspaces.models import WorkspaceMembership

        owner = user_factory()
        actor = user_factory()
        target = user_factory()
        workspace = workspace_factory(owner=owner)
        _make_membership(workspace, actor, role_slug="member")
        _make_membership(workspace, target, role_slug="member")

        api_client.force_authenticate(user=actor)
        response = api_client.delete(_remove_url(workspace, target))

        assert response.status_code == 403
        # The target is untouched.
        assert _status_of(workspace, target) == WorkspaceMembership.Status.ACTIVE

    def test_viewer_is_denied(self, api_client, workspace_factory, user_factory):
        from infrastructure.persistence.workspaces.models import WorkspaceMembership

        owner = user_factory()
        viewer = user_factory()
        target = user_factory()
        workspace = workspace_factory(owner=owner)
        _make_membership(workspace, viewer, role_slug="viewer")
        _make_membership(workspace, target, role_slug="member")

        api_client.force_authenticate(user=viewer)
        response = api_client.delete(_remove_url(workspace, target))

        assert response.status_code == 403
        assert _status_of(workspace, target) == WorkspaceMembership.Status.ACTIVE

    def test_owner_cannot_be_removed(self, api_client, workspace_factory, user_factory):
        from infrastructure.persistence.workspaces.models import WorkspaceMembership

        owner = user_factory()
        admin = user_factory()
        workspace = workspace_factory(owner=owner)
        _make_membership(workspace, owner, role_slug="owner")
        _make_membership(workspace, admin, role_slug="admin")

        api_client.force_authenticate(user=admin)
        response = api_client.delete(_remove_url(workspace, owner))

        assert response.status_code == 400
        assert _status_of(workspace, owner) == WorkspaceMembership.Status.ACTIVE

    def test_owner_cannot_remove_themselves(self, api_client, workspace_factory, user_factory):
        """Self-removal is allowed for everyone EXCEPT the owner — an owner
        leaving would orphan the workspace."""
        from infrastructure.persistence.workspaces.models import WorkspaceMembership

        owner = user_factory()
        workspace = workspace_factory(owner=owner)
        _make_membership(workspace, owner, role_slug="owner")

        api_client.force_authenticate(user=owner)
        response = api_client.delete(_remove_url(workspace, owner))

        assert response.status_code == 400
        assert _status_of(workspace, owner) == WorkspaceMembership.Status.ACTIVE

    def test_non_member_is_404(self, api_client, workspace_factory, user_factory):
        owner = user_factory()
        stranger = user_factory()
        workspace = workspace_factory(owner=owner)

        api_client.force_authenticate(user=owner)
        response = api_client.delete(_remove_url(workspace, stranger))

        assert response.status_code == 404


class TestRemoveMemberSelfService:
    def test_member_may_remove_themselves_without_manage_users(self, api_client, workspace_factory, user_factory):
        from infrastructure.persistence.workspaces.models import WorkspaceMembership

        owner = user_factory()
        leaver = user_factory()
        workspace = workspace_factory(owner=owner)
        _make_membership(workspace, leaver, role_slug="member")

        api_client.force_authenticate(user=leaver)
        response = api_client.delete(_remove_url(workspace, leaver))

        assert response.status_code == 200, response.data
        assert response.data["removed"] is True
        assert _status_of(workspace, leaver) == WorkspaceMembership.Status.SUSPENDED

    def test_leaving_does_not_notify_the_leaver(
        self, api_client, workspace_factory, user_factory, django_capture_on_commit_callbacks
    ):
        from infrastructure.persistence.notifications.models import Notification

        owner = user_factory()
        leaver = user_factory()
        workspace = workspace_factory(owner=owner)
        _make_membership(workspace, leaver, role_slug="member")

        api_client.force_authenticate(user=leaver)
        with django_capture_on_commit_callbacks(execute=True):
            api_client.delete(_remove_url(workspace, leaver))

        assert not Notification.objects.filter(recipient=leaver).exists()


class TestRemoveMemberIdempotency:
    def test_second_removal_is_a_success_noop(
        self, api_client, workspace_factory, user_factory, django_capture_on_commit_callbacks
    ):
        from infrastructure.persistence.notifications.models import Notification

        owner = user_factory()
        target = user_factory()
        workspace = workspace_factory(owner=owner)
        _make_membership(workspace, target, role_slug="member")

        api_client.force_authenticate(user=owner)
        with django_capture_on_commit_callbacks(execute=True):
            first = api_client.delete(_remove_url(workspace, target))
        notifications_after_first = Notification.objects.filter(recipient=target).count()

        with django_capture_on_commit_callbacks(execute=True):
            second = api_client.delete(_remove_url(workspace, target))

        assert first.status_code == 200
        assert second.status_code == 200
        assert second.data["removed"] is False
        assert second.data["already_revoked"] is True
        # No duplicate side effects on the no-op path.
        assert Notification.objects.filter(recipient=target).count() == notifications_after_first


class TestRemovedMemberLosesCapabilities:
    """A revoked membership is an authoritative DENY — the team fallback must never re-grant.

    Regression guard for the privilege-escalation found in the members-rbac QA
    sweep: removal soft-revokes the ``WorkspaceMembership`` but leaves the user
    on the workspace's teams, and the capability gate's team-only compatibility
    fallback then handed the removed user the seeded ``member`` role's
    permission bundle — which carries ``manage_findings``. Reads (which use a
    strict ACTIVE-membership check with no fallback) denied, writes allowed.
    """

    @staticmethod
    def _finding(workspace):
        from django.utils import timezone

        from infrastructure.persistence.findings.models import Finding

        now = timezone.now()
        return Finding.objects.create(
            workspace=workspace,
            source="cloud_posture.prowler",
            fingerprint="removed-member-fp-1",
            asset_urn="urn:aws:s3:::removed-member-bucket",
            severity="high",
            status="open",
            title="Public S3 bucket",
            first_seen_at=now,
            last_seen_at=now,
        )

    def test_removed_team_member_cannot_suppress_findings(
        self, api_client, workspace_factory, user_factory, team_factory
    ):
        from infrastructure.persistence.workspaces.models import WorkspaceMembership

        owner = user_factory()
        victim = user_factory()
        workspace = workspace_factory(owner=owner)
        _make_membership(workspace, victim, role_slug="member")
        team_factory(workspace=workspace, created_by=owner, members=[victim])

        finding = self._finding(workspace)
        status_url = f"/findings/workspaces/{workspace.id}/{finding.id}/status/"

        # Baseline: while ACTIVE the analyst legitimately carries manage_findings.
        api_client.force_authenticate(user=victim)
        assert api_client.post(status_url, {"action": "resolve"}, format="json").status_code == 200

        api_client.force_authenticate(user=owner)
        removal = api_client.delete(_remove_url(workspace, victim))
        assert removal.status_code == 200, removal.data
        assert _status_of(workspace, victim) == WorkspaceMembership.Status.SUSPENDED

        # The removed user is still on the team — the state the fallback keyed off.
        from infrastructure.persistence.team.models import Team

        assert Team.objects.filter(workspace=workspace, members__id=victim.id).exists()

        api_client.force_authenticate(user=victim)
        response = api_client.post(status_url, {"action": "suppress"}, format="json")

        assert response.status_code == 403, response.data
        finding.refresh_from_db()
        assert finding.status == "resolved", "a removed member must not mutate finding state"

    def test_removed_member_is_denied_reads_and_writes_alike(
        self, api_client, workspace_factory, user_factory, team_factory
    ):
        """No read/write asymmetry: both surfaces deny the removed member."""
        owner = user_factory()
        victim = user_factory()
        workspace = workspace_factory(owner=owner)
        _make_membership(workspace, victim, role_slug="member")
        team_factory(workspace=workspace, created_by=owner, members=[victim])
        finding = self._finding(workspace)

        api_client.force_authenticate(user=owner)
        assert api_client.delete(_remove_url(workspace, victim)).status_code == 200

        api_client.force_authenticate(user=victim)
        assert api_client.get(f"/findings/workspaces/{workspace.id}/").status_code == 403
        tags_url = f"/findings/workspaces/{workspace.id}/{finding.id}/tags/"
        assert api_client.post(tags_url, {"add": ["urgent"]}, format="json").status_code == 403

    def test_team_only_user_with_no_membership_row_keeps_the_fallback(
        self, api_client, workspace_factory, user_factory, team_factory
    ):
        """The pre-Phase-3b fallback still serves its purpose: a user who has an
        active team membership and NO ``WorkspaceMembership`` row at all (the
        un-backfilled legacy shape) keeps the seeded ``member`` bundle."""
        from infrastructure.persistence.workspaces.models import WorkspaceMembership

        owner = user_factory()
        legacy = user_factory()
        workspace = workspace_factory(owner=owner)
        team_factory(workspace=workspace, created_by=owner, members=[legacy])
        assert not WorkspaceMembership.objects.filter(workspace=workspace, user=legacy).exists()

        finding = self._finding(workspace)
        api_client.force_authenticate(user=legacy)
        response = api_client.post(
            f"/findings/workspaces/{workspace.id}/{finding.id}/status/",
            {"action": "resolve"},
            format="json",
        )

        assert response.status_code == 200, response.data

    def test_revoked_member_fails_the_workspace_membership_floor(
        self, api_client, workspace_factory, user_factory, team_factory
    ):
        """The same fallback lives on ``IsOrgOwnerOrMember`` — the membership
        floor guarding most workspace-scoped endpoints (and reused directly by
        ``components/sign_off/api/controller.py``). It must revoke too."""
        from components.workspace.api.permissions import IsOrgOwnerOrMember

        owner = user_factory()
        victim = user_factory()
        workspace = workspace_factory(owner=owner)
        _make_membership(workspace, victim, role_slug="member")
        team_factory(workspace=workspace, created_by=owner, members=[victim])

        gate = IsOrgOwnerOrMember()
        assert gate._is_member(victim, workspace) is True

        api_client.force_authenticate(user=owner)
        assert api_client.delete(_remove_url(workspace, victim)).status_code == 200

        assert gate._is_member(victim, workspace) is False
