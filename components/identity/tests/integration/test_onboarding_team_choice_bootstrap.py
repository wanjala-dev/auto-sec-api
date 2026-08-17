"""feature.onboarding_team_choice on the BOOTSTRAP path (§c) — the
``ensure_user_workspace_context`` seam the onboarding PATCH drives, plus the
``UserPatchSerializer`` field wiring that carries the choices to it.

Marked ``real_feature_flags`` to exercise the real cascade with the flag at
its shipped default (OFF) and a per-user enable rule — the dogfood rollout
shape. Mirrors the ``feature.personal_space`` per-user precedent at this
exact seam.
"""

from __future__ import annotations

import pytest

from components.identity.infrastructure.adapters.workspace_bootstrap import (
    ensure_user_workspace_context,
)
from components.shared_platform.infrastructure.services.feature_flags import (
    bump_feature_flags_version,
)
from infrastructure.persistence.core.models import FeatureFlag, FeatureFlagRule
from infrastructure.persistence.team.models import Team

pytestmark = [pytest.mark.integration, pytest.mark.django_db, pytest.mark.real_feature_flags]

FLAG_KEY = "feature.onboarding_team_choice"


def _seed_flag(*, enabled_for_user=None):
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


class TestBootstrapTeamChoice:
    def test_flag_off_ignores_inputs(self, user_factory):
        user = user_factory()
        _seed_flag()

        workspace = ensure_user_workspace_context(
            user,
            create_if_missing=True,
            workspace_name="Acme SOC",
            team_name="Detection Squad",
            include_red_team=False,
        )

        assert workspace is not None
        home = Team.objects.get(workspace=workspace, is_default=True)
        assert home.title == "General"
        assert Team.objects.filter(workspace=workspace, kind=Team.Kind.RED_TEAM).exists()

    def test_flag_on_named_team_no_red_unless_opted_in(self, user_factory):
        user = user_factory()
        _seed_flag(enabled_for_user=user)

        workspace = ensure_user_workspace_context(
            user,
            create_if_missing=True,
            workspace_name="Acme SOC",
            team_name="Detection Squad",
        )

        assert workspace is not None
        home = Team.objects.get(workspace=workspace, is_default=True)
        assert home.title == "Detection Squad"
        assert home.kind == Team.Kind.BLUE_TEAM
        assert not Team.objects.filter(workspace=workspace, kind=Team.Kind.RED_TEAM).exists()
        # The Agents team stays unconditional — the finding pipeline depends on it.
        assert Team.objects.filter(workspace=workspace, kind=Team.Kind.AI_AGENTS).exists()

    def test_flag_on_red_team_opt_in(self, user_factory):
        user = user_factory()
        _seed_flag(enabled_for_user=user)

        workspace = ensure_user_workspace_context(
            user,
            create_if_missing=True,
            workspace_name="Acme SOC",
            team_name="Detection Squad",
            include_red_team=True,
        )

        assert Team.objects.filter(workspace=workspace, kind=Team.Kind.RED_TEAM).exists()


class TestSerializerCarriesTheChoices:
    def test_patch_serializer_accepts_and_forwards_the_fields(self, user_factory):
        """The onboarding PATCH's serializer accepts team_name/include_red_team
        (write-only) and the bootstrapped workspace reflects them."""
        from components.identity.mappers.rest.identity_serializers import UserPatchSerializer

        user = user_factory()
        _seed_flag(enabled_for_user=user)

        serializer = UserPatchSerializer(
            instance=user,
            data={
                "is_onboard_complete": True,
                "workspace_name": "Acme SOC",
                "team_name": "Detection Squad",
                "include_red_team": False,
            },
            partial=True,
        )
        assert serializer.is_valid(), serializer.errors
        serializer.save()

        home = Team.objects.get(workspace__workspace_owner=user, is_default=True)
        assert home.title == "Detection Squad"
        assert not Team.objects.filter(workspace__workspace_owner=user, kind=Team.Kind.RED_TEAM).exists()
