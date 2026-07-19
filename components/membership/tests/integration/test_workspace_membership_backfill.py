"""Tests for the Phase 3a team-only WorkspaceMembership backfill.

The ``0019_backfill_team_only_workspace_memberships`` data migration
walks every active Team, finds its members, and ensures each one has
a ``WorkspaceMembership`` (``role="member"``) in the team's workspace.
Users who already have a membership are skipped — we never overwrite.

These tests hit the backfill function directly (migration modules are
importable) so they exercise the real code without relying on pytest's
migration runner.
"""

from __future__ import annotations

import importlib

import pytest
from django.apps import apps as django_apps

from infrastructure.persistence.team.models import Team
from infrastructure.persistence.workspaces.models import (
    WorkspaceMembership,
    WorkspaceRole,
)

pytestmark = pytest.mark.django_db


def _run_backfill():
    module = importlib.import_module(
        "infrastructure.persistence.workspaces.migrations.0019_backfill_team_only_workspace_memberships"
    )
    module.backfill_team_only_memberships(django_apps, schema_editor=None)


def _member_role() -> WorkspaceRole:
    """Return the seeded ``member`` system role (the backfill's target role)."""
    return WorkspaceRole.objects.get(workspace__isnull=True, slug="member")


class TestBackfillCreatesMembershipForTeamOnlyUser:
    def test_team_only_user_gets_workspace_membership(
        self, workspace_factory, user_factory, team_factory
    ) -> None:
        owner = user_factory()
        team_only_user = user_factory()
        workspace = workspace_factory(owner=owner)
        team_factory(workspace=workspace, members=[team_only_user])

        assert not WorkspaceMembership.objects.filter(
            workspace=workspace, user=team_only_user
        ).exists(), "sanity: no membership before backfill"

        _run_backfill()

        membership = WorkspaceMembership.objects.get(
            workspace=workspace, user=team_only_user
        )
        assert membership.role == "member"
        assert membership.status == WorkspaceMembership.Status.ACTIVE
        assert membership.workspace_role_id == _member_role().id


class TestBackfillDoesNotOverwrite:
    def test_existing_admin_membership_preserved(
        self, workspace_factory, user_factory, team_factory
    ) -> None:
        """Pre-existing non-member roles must survive the backfill."""
        owner = user_factory()
        admin = user_factory()
        workspace = workspace_factory(owner=owner)
        admin_role = WorkspaceRole.objects.get(workspace__isnull=True, slug="admin")
        WorkspaceMembership.objects.create(
            workspace=workspace,
            user=admin,
            role="admin",
            workspace_role=admin_role,
            persona="contributor",
            status=WorkspaceMembership.Status.ACTIVE,
        )
        team_factory(workspace=workspace, members=[admin])

        _run_backfill()

        membership = WorkspaceMembership.objects.get(workspace=workspace, user=admin)
        assert membership.role == "admin"
        assert membership.workspace_role_id == admin_role.id

    def test_suspended_membership_preserved(
        self, workspace_factory, user_factory, team_factory
    ) -> None:
        """Even an inactive/suspended prior membership is not replaced."""
        owner = user_factory()
        user = user_factory()
        workspace = workspace_factory(owner=owner)
        viewer_role = WorkspaceRole.objects.get(workspace__isnull=True, slug="viewer")
        WorkspaceMembership.objects.create(
            workspace=workspace,
            user=user,
            role="viewer",
            workspace_role=viewer_role,
            persona="contributor",
            status=WorkspaceMembership.Status.SUSPENDED,
        )
        team_factory(workspace=workspace, members=[user])

        _run_backfill()

        membership = WorkspaceMembership.objects.get(workspace=workspace, user=user)
        assert membership.status == WorkspaceMembership.Status.SUSPENDED
        assert membership.role == "viewer"


class TestBackfillIsIdempotent:
    def test_rerun_creates_nothing_new(
        self, workspace_factory, user_factory, team_factory
    ) -> None:
        owner = user_factory()
        user = user_factory()
        workspace = workspace_factory(owner=owner)
        team_factory(workspace=workspace, members=[user])

        _run_backfill()
        count_after_first = WorkspaceMembership.objects.filter(
            workspace=workspace, user=user
        ).count()

        _run_backfill()
        count_after_second = WorkspaceMembership.objects.filter(
            workspace=workspace, user=user
        ).count()

        assert count_after_first == 1
        assert count_after_second == 1


class TestBackfillIgnoresInactiveTeams:
    def test_deleted_team_does_not_trigger_backfill(
        self, workspace_factory, user_factory, team_factory
    ) -> None:
        owner = user_factory()
        user = user_factory()
        workspace = workspace_factory(owner=owner)
        team = team_factory(workspace=workspace, members=[user])
        team.status = Team.DELETED
        team.save(update_fields=["status"])

        _run_backfill()

        assert not WorkspaceMembership.objects.filter(
            workspace=workspace, user=user
        ).exists()


class TestBackfillMultipleWorkspaces:
    def test_user_on_teams_in_two_workspaces_gets_two_memberships(
        self, workspace_factory, user_factory, team_factory
    ) -> None:
        owner = user_factory()
        shared_user = user_factory()
        ws_a = workspace_factory(owner=owner)
        ws_b = workspace_factory(owner=owner)
        team_factory(workspace=ws_a, members=[shared_user])
        team_factory(workspace=ws_b, members=[shared_user])

        _run_backfill()

        assert WorkspaceMembership.objects.filter(
            workspace=ws_a, user=shared_user
        ).exists()
        assert WorkspaceMembership.objects.filter(
            workspace=ws_b, user=shared_user
        ).exists()
