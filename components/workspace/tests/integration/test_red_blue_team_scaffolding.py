"""ADR 0007 — bootstrap seeds real Blue (default) + Red teams, owner leads both.

Findings/assets are never team-scoped (that stays the workspace SSOT per ADR
0004); this only verifies the people + team plumbing.
"""

from __future__ import annotations

import pytest

from components.workspace.infrastructure.adapters.workspace_utils import (
    ensure_red_team,
    ensure_workspace_scaffolding,
)
from infrastructure.persistence.team.models import Team, TeamMembership

pytestmark = [pytest.mark.django_db]


class TestRedBlueTeamScaffolding:
    def test_scaffolding_creates_blue_default_and_red_team(self, workspace_factory):
        owner = None
        workspace = workspace_factory()
        owner = workspace.workspace_owner

        ensure_workspace_scaffolding(workspace, owner)

        blue = Team.objects.get(workspace=workspace, is_default=True)
        assert blue.kind == Team.Kind.BLUE_TEAM
        assert blue.members.filter(id=owner.id).exists()
        assert TeamMembership.objects.get(team=blue, user=owner).role == TeamMembership.Role.LEAD

        red = Team.objects.get(workspace=workspace, kind=Team.Kind.RED_TEAM)
        assert red.is_default is False
        assert red.members.filter(id=owner.id).exists()
        assert TeamMembership.objects.get(team=red, user=owner).role == TeamMembership.Role.LEAD

    def test_only_one_red_team_even_if_scaffolded_twice(self, workspace_factory):
        workspace = workspace_factory()
        owner = workspace.workspace_owner

        ensure_workspace_scaffolding(workspace, owner)
        ensure_workspace_scaffolding(workspace, owner)  # idempotent re-run

        assert Team.objects.filter(workspace=workspace, kind=Team.Kind.RED_TEAM).count() == 1
        assert Team.objects.filter(workspace=workspace, is_default=True).count() == 1

    def test_ensure_red_team_promotes_existing_owner_to_lead(self, workspace_factory):
        workspace = workspace_factory()
        owner = workspace.workspace_owner

        red_a = ensure_red_team(workspace, owner)
        red_b = ensure_red_team(workspace, owner)  # idempotent

        assert red_a.id == red_b.id
        assert red_a.kind == Team.Kind.RED_TEAM
        assert TeamMembership.objects.filter(team=red_a, user=owner).count() == 1
