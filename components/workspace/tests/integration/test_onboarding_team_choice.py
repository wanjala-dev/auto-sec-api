"""feature.onboarding_team_choice on the explicit workspace-create path (§c).

Flag OFF (the seed default): POST /workspaces/create/ behaves exactly as
today — silent "General" home team + auto Red Team; the new inputs are
ignored. Flag ON (per-user rule, the dogfood rollout shape): the operator
names the single home team via ``team_name`` and the Red Team is seeded only
on an explicit ``include_red_team: true``. The Agents team + AI Findings
board stay unconditional in BOTH modes — the finding pipeline depends on
them (``ensure_agents_board``).

Marked ``real_feature_flags`` to bypass the autouse all-flags-on fixture and
exercise the real user → workspace → global → default cascade.
"""

from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from components.shared_platform.infrastructure.services.feature_flags import (
    bump_feature_flags_version,
)
from infrastructure.persistence.core.models import FeatureFlag, FeatureFlagRule
from infrastructure.persistence.team.models import Team
from infrastructure.persistence.workspaces.models import Workspace

pytestmark = [pytest.mark.integration, pytest.mark.django_db, pytest.mark.real_feature_flags]

WORKSPACE_CREATE_URL = "/workspaces/create/"
FLAG_KEY = "feature.onboarding_team_choice"


def _seed_flag(*, enabled_for_user=None):
    """Seed the flag at its shipped default (OFF) with an optional per-user
    enable rule — the exact rollout shape (seed_feature_flags precedent)."""
    flag, _ = FeatureFlag.objects.get_or_create(
        key=FLAG_KEY,
        defaults={"default_enabled": False, "description": "test-seeded"},
    )
    if enabled_for_user is not None:
        FeatureFlagRule.objects.update_or_create(
            flag=flag,
            scope=FeatureFlagRule.Scope.USER,
            user=enabled_for_user,
            defaults={"enabled": True, "note": "onboarding-team-choice test"},
        )
    bump_feature_flags_version()


def _create_workspace(user, payload):
    client = APIClient()
    client.force_authenticate(user=user)
    response = client.post(WORKSPACE_CREATE_URL, payload, format="json")
    assert response.status_code == 201, response.data
    return Workspace.objects.get(id=response.data["id"])


class TestOnboardingTeamChoiceCreatePath:
    def test_flag_off_ignores_inputs_and_keeps_todays_behavior(self, user_factory):
        user = user_factory()
        _seed_flag()  # default OFF, no rule

        workspace = _create_workspace(
            user,
            {"workspace_name": "Acme SOC", "team_name": "Detection Squad", "include_red_team": False},
        )

        home = Team.objects.get(workspace=workspace, is_default=True)
        assert home.title == "General", "flag OFF must ignore team_name"
        assert Team.objects.filter(workspace=workspace, kind=Team.Kind.RED_TEAM).exists(), (
            "flag OFF must keep the auto Red Team (ADR 0007)"
        )

    def test_flag_on_names_home_team_and_skips_red_team_by_default(self, user_factory):
        user = user_factory()
        _seed_flag(enabled_for_user=user)

        workspace = _create_workspace(
            user,
            {"workspace_name": "Acme SOC", "team_name": "Detection Squad"},
        )

        home = Team.objects.get(workspace=workspace, is_default=True)
        assert home.title == "Detection Squad"
        assert home.kind == Team.Kind.BLUE_TEAM, "the named home team is still the Blue team"
        assert not Team.objects.filter(workspace=workspace, kind=Team.Kind.RED_TEAM).exists(), (
            "no Red Team unless explicitly opted in"
        )

    def test_flag_on_red_team_is_created_when_opted_in(self, user_factory):
        user = user_factory()
        _seed_flag(enabled_for_user=user)

        workspace = _create_workspace(
            user,
            {"workspace_name": "Acme SOC", "team_name": "Detection Squad", "include_red_team": True},
        )

        assert Team.objects.filter(workspace=workspace, kind=Team.Kind.RED_TEAM).exists()

    def test_flag_on_blank_team_name_falls_back_to_general(self, user_factory):
        user = user_factory()
        _seed_flag(enabled_for_user=user)

        workspace = _create_workspace(user, {"workspace_name": "Acme SOC", "team_name": "   "})

        assert Team.objects.get(workspace=workspace, is_default=True).title == "General"

    def test_agents_team_is_unconditional_in_both_modes(self, user_factory):
        flagged = user_factory()
        unflagged = user_factory()
        _seed_flag(enabled_for_user=flagged)

        ws_on = _create_workspace(flagged, {"workspace_name": "Flag On", "team_name": "Squad"})
        ws_off = _create_workspace(unflagged, {"workspace_name": "Flag Off"})

        for workspace in (ws_on, ws_off):
            assert Team.objects.filter(workspace=workspace, kind=Team.Kind.AI_AGENTS).exists(), (
                "the finding pipeline depends on the Agents team — never gated"
            )
