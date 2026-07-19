"""Unit tests for TeamMembershipPolicyService domain policy service."""

from __future__ import annotations

import pytest

from components.team.domain.policies.team_membership_policy_service import (
    DEFAULT_ORG_TEAM_TITLE,
    DEFAULT_PERSONAL_TEAM_TITLE,
    TeamMembershipPolicyService,
)


class TestTeamMembershipPolicyServiceInstantiation:
    """Tests for service instantiation."""

    def test_can_instantiate_service(self) -> None:
        """Should create a new instance of TeamMembershipPolicyService."""
        service = TeamMembershipPolicyService()
        assert service is not None
        assert isinstance(service, TeamMembershipPolicyService)

    def test_multiple_instances_are_independent(self) -> None:
        """Should create independent instances of the service."""
        service1 = TeamMembershipPolicyService()
        service2 = TeamMembershipPolicyService()

        assert service1 is not service2


class TestDefaultTeamTitle:
    """Tests for the default_team_title method."""

    def test_returns_personal_team_title_when_workspace_is_personal(self) -> None:
        """Should return DEFAULT_PERSONAL_TEAM_TITLE for personal workspace."""
        service = TeamMembershipPolicyService()

        title = service.default_team_title(is_personal_workspace=True)

        assert title == DEFAULT_PERSONAL_TEAM_TITLE
        assert title == "Family"

    def test_returns_org_team_title_when_workspace_is_organizational(self) -> None:
        """Should return DEFAULT_ORG_TEAM_TITLE for organizational workspace."""
        service = TeamMembershipPolicyService()

        title = service.default_team_title(is_personal_workspace=False)

        assert title == DEFAULT_ORG_TEAM_TITLE
        assert title == "General"

    def test_returns_different_titles_for_personal_vs_org(self) -> None:
        """Should return different titles for personal vs organizational workspaces."""
        service = TeamMembershipPolicyService()

        personal_title = service.default_team_title(is_personal_workspace=True)
        org_title = service.default_team_title(is_personal_workspace=False)

        assert personal_title != org_title
        assert personal_title == "Family"
        assert org_title == "General"

    def test_default_team_title_is_consistent_across_calls(self) -> None:
        """Should return consistent title values across multiple calls."""
        service = TeamMembershipPolicyService()

        title1 = service.default_team_title(is_personal_workspace=True)
        title2 = service.default_team_title(is_personal_workspace=True)
        title3 = service.default_team_title(is_personal_workspace=True)

        assert title1 == title2 == title3

    def test_default_team_title_uses_keyword_argument(self) -> None:
        """Should require is_personal_workspace as keyword argument."""
        service = TeamMembershipPolicyService()

        # This should work with keyword argument
        title = service.default_team_title(is_personal_workspace=True)
        assert title == "Family"


class TestShouldActivateTeam:
    """Tests for the should_activate_team method."""

    def test_returns_true_when_statuses_differ(self) -> None:
        """Should return True when current_status differs from active_status."""
        service = TeamMembershipPolicyService()

        result = service.should_activate_team(
            current_status="inactive",
            active_status="active",
        )

        assert result is True

    def test_returns_false_when_statuses_are_identical(self) -> None:
        """Should return False when statuses are identical."""
        service = TeamMembershipPolicyService()

        result = service.should_activate_team(
            current_status="active",
            active_status="active",
        )

        assert result is False

    def test_returns_false_when_both_statuses_are_inactive(self) -> None:
        """Should return False when both statuses are the same inactive value."""
        service = TeamMembershipPolicyService()

        result = service.should_activate_team(
            current_status="deleted",
            active_status="deleted",
        )

        assert result is False

    def test_returns_true_when_current_deleted_and_active_is_active(self) -> None:
        """Should return True when transitioning from deleted to active."""
        service = TeamMembershipPolicyService()

        result = service.should_activate_team(
            current_status="deleted",
            active_status="active",
        )

        assert result is True

    def test_returns_true_when_current_suspended_and_active_is_active(self) -> None:
        """Should return True when transitioning from suspended to active."""
        service = TeamMembershipPolicyService()

        result = service.should_activate_team(
            current_status="suspended",
            active_status="active",
        )

        assert result is True

    def test_is_case_sensitive(self) -> None:
        """Should treat status comparison as case-sensitive."""
        service = TeamMembershipPolicyService()

        result1 = service.should_activate_team(
            current_status="Active",
            active_status="active",
        )

        assert result1 is True  # Different case means different statuses

    def test_compares_exact_strings(self) -> None:
        """Should do exact string comparison without trimming."""
        service = TeamMembershipPolicyService()

        result = service.should_activate_team(
            current_status="active ",
            active_status="active",
        )

        assert result is True  # Whitespace difference matters

    def test_should_activate_team_with_empty_strings(self) -> None:
        """Should handle empty string comparisons."""
        service = TeamMembershipPolicyService()

        result = service.should_activate_team(
            current_status="",
            active_status="",
        )

        assert result is False

    def test_should_activate_team_with_arbitrary_strings(self) -> None:
        """Should work with any arbitrary string values."""
        service = TeamMembershipPolicyService()

        result = service.should_activate_team(
            current_status="state_a",
            active_status="state_b",
        )

        assert result is True


class TestProfileContextUpdates:
    """Tests for the profile_context_updates method."""

    def test_returns_empty_dict_when_no_updates_needed(self) -> None:
        """Should return empty dict when no context updates are needed."""
        service = TeamMembershipPolicyService()

        updates = service.profile_context_updates(
            current_active_workspace_id=123,
            current_active_team_id=456,
            workspace_id=123,
            team_id=456,
            update_active_context=False,
        )

        assert updates == {}

    def test_adds_workspace_id_when_provided_and_no_current_workspace(self) -> None:
        """Should add workspace_id when provided and current_active_workspace_id is None."""
        service = TeamMembershipPolicyService()

        updates = service.profile_context_updates(
            current_active_workspace_id=None,
            current_active_team_id=456,
            workspace_id=789,
            team_id=456,
            update_active_context=False,
        )

        assert updates == {"active_workspace_id": 789}

    def test_adds_team_id_when_provided_and_no_current_team(self) -> None:
        """Should add team_id when provided and current_active_team_id is None."""
        service = TeamMembershipPolicyService()

        updates = service.profile_context_updates(
            current_active_workspace_id=123,
            current_active_team_id=None,
            workspace_id=123,
            team_id=999,
            update_active_context=False,
        )

        assert updates == {"active_team_id": 999}

    def test_adds_both_ids_when_both_are_none(self) -> None:
        """Should add both IDs when neither current value exists."""
        service = TeamMembershipPolicyService()

        updates = service.profile_context_updates(
            current_active_workspace_id=None,
            current_active_team_id=None,
            workspace_id=123,
            team_id=456,
            update_active_context=False,
        )

        assert updates == {
            "active_workspace_id": 123,
            "active_team_id": 456,
        }

    def test_updates_workspace_when_update_context_and_different(self) -> None:
        """Should update workspace_id when update_active_context=True and values differ."""
        service = TeamMembershipPolicyService()

        updates = service.profile_context_updates(
            current_active_workspace_id=123,
            current_active_team_id=456,
            workspace_id=789,
            team_id=456,
            update_active_context=True,
        )

        assert updates == {"active_workspace_id": 789}

    def test_updates_team_when_update_context_and_different(self) -> None:
        """Should update team_id when update_active_context=True and values differ."""
        service = TeamMembershipPolicyService()

        updates = service.profile_context_updates(
            current_active_workspace_id=123,
            current_active_team_id=456,
            workspace_id=123,
            team_id=999,
            update_active_context=True,
        )

        assert updates == {"active_team_id": 999}

    def test_updates_both_when_update_context_and_both_different(self) -> None:
        """Should update both IDs when update_active_context=True and both differ."""
        service = TeamMembershipPolicyService()

        updates = service.profile_context_updates(
            current_active_workspace_id=123,
            current_active_team_id=456,
            workspace_id=789,
            team_id=999,
            update_active_context=True,
        )

        assert updates == {
            "active_workspace_id": 789,
            "active_team_id": 999,
        }

    def test_no_updates_when_update_context_and_all_same(self) -> None:
        """Should return empty dict when update_active_context=True but values match."""
        service = TeamMembershipPolicyService()

        updates = service.profile_context_updates(
            current_active_workspace_id=123,
            current_active_team_id=456,
            workspace_id=123,
            team_id=456,
            update_active_context=True,
        )

        assert updates == {}

    def test_ignores_workspace_when_none_provided_without_current(self) -> None:
        """Should not add workspace_id when it's None, even if no current."""
        service = TeamMembershipPolicyService()

        updates = service.profile_context_updates(
            current_active_workspace_id=None,
            current_active_team_id=456,
            workspace_id=None,
            team_id=456,
            update_active_context=False,
        )

        assert updates == {}

    def test_ignores_team_when_none_provided_without_current(self) -> None:
        """Should not add team_id when it's None, even if no current."""
        service = TeamMembershipPolicyService()

        updates = service.profile_context_updates(
            current_active_workspace_id=123,
            current_active_team_id=None,
            workspace_id=123,
            team_id=None,
            update_active_context=False,
        )

        assert updates == {}

    def test_ignores_provided_values_when_current_exists_and_no_update_flag(self) -> None:
        """Should not update existing values when update_active_context=False."""
        service = TeamMembershipPolicyService()

        updates = service.profile_context_updates(
            current_active_workspace_id=123,
            current_active_team_id=456,
            workspace_id=789,
            team_id=999,
            update_active_context=False,
        )

        assert updates == {}

    def test_handles_zero_as_valid_id(self) -> None:
        """Should treat 0 as a valid ID, not as falsy."""
        service = TeamMembershipPolicyService()

        updates = service.profile_context_updates(
            current_active_workspace_id=None,
            current_active_team_id=456,
            workspace_id=0,
            team_id=456,
            update_active_context=False,
        )

        assert updates == {"active_workspace_id": 0}

    def test_handles_negative_ids(self) -> None:
        """Should handle negative ID values."""
        service = TeamMembershipPolicyService()

        updates = service.profile_context_updates(
            current_active_workspace_id=None,
            current_active_team_id=None,
            workspace_id=-1,
            team_id=-2,
            update_active_context=False,
        )

        assert updates == {
            "active_workspace_id": -1,
            "active_team_id": -2,
        }

    def test_preserves_current_false_value_without_update_flag(self) -> None:
        """Should not overwrite existing False values without update flag."""
        service = TeamMembershipPolicyService()

        updates = service.profile_context_updates(
            current_active_workspace_id=False,
            current_active_team_id=456,
            workspace_id=123,
            team_id=456,
            update_active_context=False,
        )

        assert updates == {}

    def test_workspace_id_priority_over_team_id_in_update_logic(self) -> None:
        """Should handle workspace and team updates independently."""
        service = TeamMembershipPolicyService()

        # Only workspace differs
        updates1 = service.profile_context_updates(
            current_active_workspace_id=123,
            current_active_team_id=456,
            workspace_id=789,
            team_id=456,
            update_active_context=True,
        )
        assert "active_workspace_id" in updates1
        assert "active_team_id" not in updates1

        # Only team differs
        updates2 = service.profile_context_updates(
            current_active_workspace_id=123,
            current_active_team_id=456,
            workspace_id=123,
            team_id=999,
            update_active_context=True,
        )
        assert "active_workspace_id" not in updates2
        assert "active_team_id" in updates2

    def test_complex_scenario_mixed_conditions(self) -> None:
        """Should handle complex scenario with mixed None and existing values."""
        service = TeamMembershipPolicyService()

        # Current workspace is set, team is None; providing new team
        updates = service.profile_context_updates(
            current_active_workspace_id=123,
            current_active_team_id=None,
            workspace_id=123,
            team_id=456,
            update_active_context=False,
        )

        assert updates == {"active_team_id": 456}
        assert "active_workspace_id" not in updates

    def test_update_flag_overrides_none_check_for_workspace(self) -> None:
        """Should update workspace even if current exists, when update flag is True."""
        service = TeamMembershipPolicyService()

        updates = service.profile_context_updates(
            current_active_workspace_id=123,
            current_active_team_id=456,
            workspace_id=789,
            team_id=456,
            update_active_context=True,
        )

        assert "active_workspace_id" in updates
        assert updates["active_workspace_id"] == 789

    def test_return_type_is_dict(self) -> None:
        """Should always return a dictionary."""
        service = TeamMembershipPolicyService()

        updates = service.profile_context_updates(
            current_active_workspace_id=123,
            current_active_team_id=456,
            workspace_id=123,
            team_id=456,
            update_active_context=False,
        )

        assert isinstance(updates, dict)

    def test_dict_keys_are_exact_strings(self) -> None:
        """Should use exact string keys in returned dictionary."""
        service = TeamMembershipPolicyService()

        updates = service.profile_context_updates(
            current_active_workspace_id=None,
            current_active_team_id=None,
            workspace_id=123,
            team_id=456,
            update_active_context=False,
        )

        assert "active_workspace_id" in updates
        assert "active_team_id" in updates
        # Ensure keys are exactly as expected
        keys = set(updates.keys())
        assert keys == {"active_workspace_id", "active_team_id"}


class TestProfileContextUpdatesEdgeCases:
    """Edge cases and boundary tests for profile_context_updates."""

    def test_same_id_for_workspace_and_team(self) -> None:
        """Should handle case where workspace_id and team_id have same value."""
        service = TeamMembershipPolicyService()

        updates = service.profile_context_updates(
            current_active_workspace_id=None,
            current_active_team_id=None,
            workspace_id=100,
            team_id=100,
            update_active_context=False,
        )

        assert updates == {
            "active_workspace_id": 100,
            "active_team_id": 100,
        }

    def test_large_id_values(self) -> None:
        """Should handle very large ID values."""
        service = TeamMembershipPolicyService()

        large_id = 9999999999

        updates = service.profile_context_updates(
            current_active_workspace_id=None,
            current_active_team_id=None,
            workspace_id=large_id,
            team_id=large_id,
            update_active_context=False,
        )

        assert updates["active_workspace_id"] == large_id
        assert updates["active_team_id"] == large_id

    def test_alternating_update_flag_behavior(self) -> None:
        """Should correctly differentiate behavior based on update flag."""
        service = TeamMembershipPolicyService()

        # Same inputs, different update flags
        updates_with_flag = service.profile_context_updates(
            current_active_workspace_id=123,
            current_active_team_id=456,
            workspace_id=789,
            team_id=999,
            update_active_context=True,
        )

        updates_without_flag = service.profile_context_updates(
            current_active_workspace_id=123,
            current_active_team_id=456,
            workspace_id=789,
            team_id=999,
            update_active_context=False,
        )

        assert len(updates_with_flag) > 0
        assert len(updates_without_flag) == 0
