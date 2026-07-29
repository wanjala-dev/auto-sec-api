"""The seed_security_teams command backfills Blue+Red for existing workspaces
(ADR 0007) — including the edge case a workspace had no default team at all
(the data-migration backfill's gap)."""

from __future__ import annotations

import pytest
from django.core.management import call_command

from infrastructure.persistence.team.models import Team

pytestmark = [pytest.mark.django_db]


class TestSeedSecurityTeamsCommand:
    def test_seeds_blue_and_red_for_a_workspace_with_no_teams(self, workspace_factory):
        workspace = workspace_factory()
        # No scaffolding has run — the workspace has no default team (the gap).
        assert not Team.objects.filter(workspace=workspace, is_default=True).exists()

        call_command("seed_security_teams", workspace=str(workspace.id))

        blue = Team.objects.get(workspace=workspace, is_default=True)
        assert blue.kind == Team.Kind.BLUE_TEAM
        red = Team.objects.get(workspace=workspace, kind=Team.Kind.RED_TEAM)
        assert red.is_default is False
        owner = workspace.workspace_owner
        assert blue.members.filter(id=owner.id).exists()
        assert red.members.filter(id=owner.id).exists()

    def test_is_idempotent(self, workspace_factory):
        workspace = workspace_factory()
        call_command("seed_security_teams", workspace=str(workspace.id))
        call_command("seed_security_teams", workspace=str(workspace.id))
        assert Team.objects.filter(workspace=workspace, is_default=True).count() == 1
        assert Team.objects.filter(workspace=workspace, kind=Team.Kind.RED_TEAM).count() == 1
