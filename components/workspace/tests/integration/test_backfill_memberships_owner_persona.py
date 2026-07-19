"""Integration tests for `backfill_memberships` covering owner persona."""
from __future__ import annotations

import pytest
from django.core.management import call_command

from infrastructure.persistence.workspaces.models import Workspace, WorkspaceMembership


@pytest.mark.django_db
class TestBackfillMembershipsOwnerPersona:
    """Regression coverage for the bug where workspace owners ended up with
    `persona=contributor` because the backfill command only set role and
    relied on the model default, which is CONTRIBUTOR. The frontend
    `useActivePersona` then rendered the contributor sidebar even though
    the role policy returned the full admin section list.
    """

    def _backfill(self, workspace_id):
        call_command("backfill_memberships", "--workspace-id", str(workspace_id))

    def test_creates_owner_membership_with_admin_persona_for_teamspace(
        self, workspace_factory, user_factory
    ):
        owner = user_factory()
        workspace = workspace_factory(owner=owner)
        Workspace.objects.filter(id=workspace.id).update(workspace_type="teamspace")
        WorkspaceMembership.objects.filter(workspace=workspace, user=owner).delete()

        self._backfill(workspace.id)

        membership = WorkspaceMembership.objects.get(workspace=workspace, user=owner)
        assert membership.role == WorkspaceMembership.Role.OWNER
        assert membership.persona == WorkspaceMembership.Persona.ADMIN

    def test_creates_owner_membership_with_private_persona_for_personal_workspace(
        self, workspace_factory, user_factory
    ):
        owner = user_factory()
        workspace = workspace_factory(owner=owner)
        Workspace.objects.filter(id=workspace.id).update(workspace_type="personal")
        WorkspaceMembership.objects.filter(workspace=workspace, user=owner).delete()

        self._backfill(workspace.id)

        membership = WorkspaceMembership.objects.get(workspace=workspace, user=owner)
        assert membership.role == WorkspaceMembership.Role.OWNER
        assert membership.persona == WorkspaceMembership.Persona.PRIVATE

    def test_repairs_owner_with_stale_contributor_persona(
        self, workspace_factory, user_factory
    ):
        # Reproduces the demo bug: owner row with persona=contributor.
        # Backend role policy returns admin sections; frontend renders
        # contributor sidebar because it reads persona straight.
        owner = user_factory()
        workspace = workspace_factory(owner=owner)
        Workspace.objects.filter(id=workspace.id).update(workspace_type="teamspace")
        WorkspaceMembership.objects.update_or_create(
            workspace=workspace,
            user=owner,
            defaults={
                "role": WorkspaceMembership.Role.OWNER,
                "persona": WorkspaceMembership.Persona.CONTRIBUTOR,
                "status": WorkspaceMembership.Status.ACTIVE,
            },
        )

        self._backfill(workspace.id)

        membership = WorkspaceMembership.objects.get(workspace=workspace, user=owner)
        assert membership.persona == WorkspaceMembership.Persona.ADMIN

    def test_does_not_overwrite_legitimately_customised_persona(
        self, workspace_factory, user_factory
    ):
        # An owner deliberately set as AGENTIC / BOARD_MEMBER / etc.
        # should not get clobbered to ADMIN by the backfill — only
        # CONTRIBUTOR (the model default) is treated as drift.
        owner = user_factory()
        workspace = workspace_factory(owner=owner)
        Workspace.objects.filter(id=workspace.id).update(workspace_type="teamspace")
        WorkspaceMembership.objects.update_or_create(
            workspace=workspace,
            user=owner,
            defaults={
                "role": WorkspaceMembership.Role.OWNER,
                "persona": WorkspaceMembership.Persona.AGENTIC,
                "status": WorkspaceMembership.Status.ACTIVE,
            },
        )

        self._backfill(workspace.id)

        membership = WorkspaceMembership.objects.get(workspace=workspace, user=owner)
        assert membership.persona == WorkspaceMembership.Persona.AGENTIC

    def test_dry_run_does_not_persist_persona_repair(
        self, workspace_factory, user_factory
    ):
        owner = user_factory()
        workspace = workspace_factory(owner=owner)
        Workspace.objects.filter(id=workspace.id).update(workspace_type="teamspace")
        WorkspaceMembership.objects.update_or_create(
            workspace=workspace,
            user=owner,
            defaults={
                "role": WorkspaceMembership.Role.OWNER,
                "persona": WorkspaceMembership.Persona.CONTRIBUTOR,
                "status": WorkspaceMembership.Status.ACTIVE,
            },
        )

        call_command("backfill_memberships", "--workspace-id", str(workspace.id), "--dry-run")

        membership = WorkspaceMembership.objects.get(workspace=workspace, user=owner)
        assert membership.persona == WorkspaceMembership.Persona.CONTRIBUTOR
