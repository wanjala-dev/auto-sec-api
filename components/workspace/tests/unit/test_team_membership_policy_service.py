from __future__ import annotations

from components.team.domain.policies.team_membership_policy_service import (
    DEFAULT_ORG_TEAM_TITLE,
    DEFAULT_PERSONAL_TEAM_TITLE,
    TeamMembershipPolicyService,
)


def test_default_team_title_uses_personal_workspace_variant():
    service = TeamMembershipPolicyService()

    assert (
        service.default_team_title(is_personal_workspace=True)
        == DEFAULT_PERSONAL_TEAM_TITLE
    )
    assert (
        service.default_team_title(is_personal_workspace=False)
        == DEFAULT_ORG_TEAM_TITLE
    )


def test_profile_context_updates_fill_empty_context_without_overwrite():
    service = TeamMembershipPolicyService()

    updates = service.profile_context_updates(
        current_active_workspace_id=None,
        current_active_team_id=None,
        workspace_id="workspace-1",
        team_id=42,
        update_active_context=False,
    )

    assert updates == {
        "active_workspace_id": "workspace-1",
        "active_team_id": 42,
    }


def test_profile_context_updates_force_active_context_when_requested():
    service = TeamMembershipPolicyService()

    updates = service.profile_context_updates(
        current_active_workspace_id="workspace-1",
        current_active_team_id=7,
        workspace_id="workspace-2",
        team_id=42,
        update_active_context=True,
    )

    assert updates == {
        "active_workspace_id": "workspace-2",
        "active_team_id": 42,
    }
