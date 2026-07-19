"""Unit tests for TeamEntity domain entity."""

from __future__ import annotations

import datetime
from dataclasses import FrozenInstanceError
from uuid import UUID, uuid4

import pytest

from components.team.domain.entities.team_entity import TeamEntity
from components.team.domain.enums import TeamKind, TeamStatus


class TestTeamEntityConstruction:
    """Tests for TeamEntity instantiation and validation."""

    def test_create_team_entity_with_all_required_fields(self) -> None:
        """Should create a valid TeamEntity with all required fields."""
        workspace_id = uuid4()
        created_at = datetime.datetime(2024, 1, 1, 12, 0, 0)

        team = TeamEntity(
            id=1,
            workspace_id=workspace_id,
            title="Engineering Team",
            created_by_id=42,
            created_at=created_at,
            plan_id=10,
            kind=TeamKind.DEPARTMENT,
            status=TeamStatus.ACTIVE,
            privacy="public",
        )

        assert team.id == 1
        assert team.workspace_id == workspace_id
        assert team.title == "Engineering Team"
        assert team.created_by_id == 42
        assert team.created_at == created_at
        assert team.plan_id == 10
        assert team.kind == TeamKind.DEPARTMENT
        assert team.status == TeamStatus.ACTIVE
        assert team.privacy == "public"

    def test_create_team_entity_with_optional_fields(self) -> None:
        """Should create a TeamEntity with all optional fields."""
        workspace_id = uuid4()
        created_at = datetime.datetime(2024, 1, 1, 12, 0, 0)
        plan_end_date = datetime.datetime(2025, 1, 1, 12, 0, 0)

        team = TeamEntity(
            id=2,
            workspace_id=workspace_id,
            title="Premium Team",
            created_by_id=43,
            created_at=created_at,
            plan_id=20,
            kind=TeamKind.PROJECT_TEAM,
            status=TeamStatus.ACTIVE,
            privacy="private",
            plan_status="canceled",
            plan_end_date=plan_end_date,
            stripe_customer_id="cus_abc123",
            stripe_subscription_id="sub_xyz789",
        )

        assert team.plan_status == "canceled"
        assert team.plan_end_date == plan_end_date
        assert team.stripe_customer_id == "cus_abc123"
        assert team.stripe_subscription_id == "sub_xyz789"

    def test_create_team_entity_with_default_plan_status(self) -> None:
        """Should default plan_status to 'active' when not provided."""
        workspace_id = uuid4()
        created_at = datetime.datetime(2024, 1, 1, 12, 0, 0)

        team = TeamEntity(
            id=3,
            workspace_id=workspace_id,
            title="Default Plan Team",
            created_by_id=44,
            created_at=created_at,
            plan_id=30,
            kind=TeamKind.AI_AGENTS,
            status=TeamStatus.ACTIVE,
            privacy="public",
        )

        assert team.plan_status == "active"

    def test_raises_value_error_when_workspace_id_is_none(self) -> None:
        """Should raise ValueError when workspace_id is None."""
        created_at = datetime.datetime(2024, 1, 1, 12, 0, 0)

        with pytest.raises(ValueError, match="TeamEntity.workspace_id is required"):
            TeamEntity(
                id=4,
                workspace_id=None,
                title="Invalid Team",
                created_by_id=45,
                created_at=created_at,
                plan_id=40,
                kind=TeamKind.DEPARTMENT,
                status=TeamStatus.ACTIVE,
                privacy="public",
            )

    def test_raises_value_error_when_title_is_none(self) -> None:
        """Should raise ValueError when title is None."""
        workspace_id = uuid4()
        created_at = datetime.datetime(2024, 1, 1, 12, 0, 0)

        with pytest.raises(ValueError, match="TeamEntity.title is required"):
            TeamEntity(
                id=5,
                workspace_id=workspace_id,
                title=None,
                created_by_id=46,
                created_at=created_at,
                plan_id=50,
                kind=TeamKind.DEPARTMENT,
                status=TeamStatus.ACTIVE,
                privacy="public",
            )

    def test_raises_value_error_when_title_is_empty_string(self) -> None:
        """Should raise ValueError when title is an empty string."""
        workspace_id = uuid4()
        created_at = datetime.datetime(2024, 1, 1, 12, 0, 0)

        with pytest.raises(ValueError, match="TeamEntity.title is required"):
            TeamEntity(
                id=6,
                workspace_id=workspace_id,
                title="",
                created_by_id=47,
                created_at=created_at,
                plan_id=60,
                kind=TeamKind.DEPARTMENT,
                status=TeamStatus.ACTIVE,
                privacy="public",
            )


class TestTeamEntityFrozenness:
    """Tests for TeamEntity immutability."""

    def test_team_entity_is_frozen(self) -> None:
        """Should not allow modification of TeamEntity fields after creation."""
        workspace_id = uuid4()
        created_at = datetime.datetime(2024, 1, 1, 12, 0, 0)

        team = TeamEntity(
            id=7,
            workspace_id=workspace_id,
            title="Frozen Team",
            created_by_id=48,
            created_at=created_at,
            plan_id=70,
            kind=TeamKind.DEPARTMENT,
            status=TeamStatus.ACTIVE,
            privacy="public",
        )

        with pytest.raises(FrozenInstanceError):
            team.title = "New Title"

    def test_team_entity_cannot_add_new_attributes(self) -> None:
        """Should not allow adding new attributes to frozen TeamEntity."""
        workspace_id = uuid4()
        created_at = datetime.datetime(2024, 1, 1, 12, 0, 0)

        team = TeamEntity(
            id=8,
            workspace_id=workspace_id,
            title="Immutable Team",
            created_by_id=49,
            created_at=created_at,
            plan_id=80,
            kind=TeamKind.DEPARTMENT,
            status=TeamStatus.ACTIVE,
            privacy="public",
        )

        with pytest.raises(FrozenInstanceError):
            team.new_field = "value"


class TestTeamEntityIsActiveProperty:
    """Tests for the is_active computed property."""

    def test_is_active_returns_true_when_status_is_active(self) -> None:
        """Should return True when status equals TeamStatus.ACTIVE."""
        workspace_id = uuid4()
        created_at = datetime.datetime(2024, 1, 1, 12, 0, 0)

        team = TeamEntity(
            id=9,
            workspace_id=workspace_id,
            title="Active Team",
            created_by_id=50,
            created_at=created_at,
            plan_id=90,
            kind=TeamKind.DEPARTMENT,
            status=TeamStatus.ACTIVE,
            privacy="public",
        )

        assert team.is_active is True

    def test_is_active_returns_false_when_status_is_deleted(self) -> None:
        """Should return False when status equals TeamStatus.DELETED."""
        workspace_id = uuid4()
        created_at = datetime.datetime(2024, 1, 1, 12, 0, 0)

        team = TeamEntity(
            id=10,
            workspace_id=workspace_id,
            title="Deleted Team",
            created_by_id=51,
            created_at=created_at,
            plan_id=100,
            kind=TeamKind.DEPARTMENT,
            status=TeamStatus.DELETED,
            privacy="public",
        )

        assert team.is_active is False

    def test_is_active_returns_false_for_arbitrary_status(self) -> None:
        """Should return False for any status other than TeamStatus.ACTIVE."""
        workspace_id = uuid4()
        created_at = datetime.datetime(2024, 1, 1, 12, 0, 0)

        team = TeamEntity(
            id=11,
            workspace_id=workspace_id,
            title="Custom Status Team",
            created_by_id=52,
            created_at=created_at,
            plan_id=110,
            kind=TeamKind.DEPARTMENT,
            status="suspended",
            privacy="public",
        )

        assert team.is_active is False


class TestTeamEntityIsAiAgentsProperty:
    """Tests for the is_ai_agents computed property."""

    def test_is_ai_agents_returns_true_when_kind_is_ai_agents(self) -> None:
        """Should return True when kind equals TeamKind.AI_AGENTS."""
        workspace_id = uuid4()
        created_at = datetime.datetime(2024, 1, 1, 12, 0, 0)

        team = TeamEntity(
            id=12,
            workspace_id=workspace_id,
            title="AI Agents Team",
            created_by_id=53,
            created_at=created_at,
            plan_id=120,
            kind=TeamKind.AI_AGENTS,
            status=TeamStatus.ACTIVE,
            privacy="public",
        )

        assert team.is_ai_agents is True

    def test_is_ai_agents_returns_false_when_kind_is_department(self) -> None:
        """Should return False when kind equals TeamKind.DEPARTMENT."""
        workspace_id = uuid4()
        created_at = datetime.datetime(2024, 1, 1, 12, 0, 0)

        team = TeamEntity(
            id=13,
            workspace_id=workspace_id,
            title="Department Team",
            created_by_id=54,
            created_at=created_at,
            plan_id=130,
            kind=TeamKind.DEPARTMENT,
            status=TeamStatus.ACTIVE,
            privacy="public",
        )

        assert team.is_ai_agents is False

    def test_is_ai_agents_returns_false_when_kind_is_project_team(self) -> None:
        """Should return False when kind equals TeamKind.PROJECT_TEAM."""
        workspace_id = uuid4()
        created_at = datetime.datetime(2024, 1, 1, 12, 0, 0)

        team = TeamEntity(
            id=14,
            workspace_id=workspace_id,
            title="Project Team",
            created_by_id=55,
            created_at=created_at,
            plan_id=140,
            kind=TeamKind.PROJECT_TEAM,
            status=TeamStatus.ACTIVE,
            privacy="public",
        )

        assert team.is_ai_agents is False

    def test_is_ai_agents_returns_false_for_arbitrary_kind(self) -> None:
        """Should return False for any kind other than TeamKind.AI_AGENTS."""
        workspace_id = uuid4()
        created_at = datetime.datetime(2024, 1, 1, 12, 0, 0)

        team = TeamEntity(
            id=15,
            workspace_id=workspace_id,
            title="Custom Kind Team",
            created_by_id=56,
            created_at=created_at,
            plan_id=150,
            kind="custom_kind",
            status=TeamStatus.ACTIVE,
            privacy="public",
        )

        assert team.is_ai_agents is False


class TestTeamEntityEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_team_entity_with_very_long_title(self) -> None:
        """Should accept very long title strings."""
        workspace_id = uuid4()
        created_at = datetime.datetime(2024, 1, 1, 12, 0, 0)
        long_title = "A" * 500

        team = TeamEntity(
            id=16,
            workspace_id=workspace_id,
            title=long_title,
            created_by_id=57,
            created_at=created_at,
            plan_id=160,
            kind=TeamKind.DEPARTMENT,
            status=TeamStatus.ACTIVE,
            privacy="public",
        )

        assert team.title == long_title
        assert len(team.title) == 500

    def test_team_entity_with_special_characters_in_title(self) -> None:
        """Should accept special characters in title."""
        workspace_id = uuid4()
        created_at = datetime.datetime(2024, 1, 1, 12, 0, 0)
        special_title = "Team @ #2024 & Operations (ÄÖÜ)"

        team = TeamEntity(
            id=17,
            workspace_id=workspace_id,
            title=special_title,
            created_by_id=58,
            created_at=created_at,
            plan_id=170,
            kind=TeamKind.DEPARTMENT,
            status=TeamStatus.ACTIVE,
            privacy="public",
        )

        assert team.title == special_title

    def test_team_entity_with_zero_id(self) -> None:
        """Should accept zero as a valid id."""
        workspace_id = uuid4()
        created_at = datetime.datetime(2024, 1, 1, 12, 0, 0)

        team = TeamEntity(
            id=0,
            workspace_id=workspace_id,
            title="Zero ID Team",
            created_by_id=59,
            created_at=created_at,
            plan_id=180,
            kind=TeamKind.DEPARTMENT,
            status=TeamStatus.ACTIVE,
            privacy="public",
        )

        assert team.id == 0

    def test_team_entity_with_negative_id(self) -> None:
        """Should accept negative ids."""
        workspace_id = uuid4()
        created_at = datetime.datetime(2024, 1, 1, 12, 0, 0)

        team = TeamEntity(
            id=-1,
            workspace_id=workspace_id,
            title="Negative ID Team",
            created_by_id=60,
            created_at=created_at,
            plan_id=190,
            kind=TeamKind.DEPARTMENT,
            status=TeamStatus.ACTIVE,
            privacy="public",
        )

        assert team.id == -1

    def test_team_entity_with_none_plan_end_date(self) -> None:
        """Should accept None for plan_end_date."""
        workspace_id = uuid4()
        created_at = datetime.datetime(2024, 1, 1, 12, 0, 0)

        team = TeamEntity(
            id=18,
            workspace_id=workspace_id,
            title="No End Date Team",
            created_by_id=61,
            created_at=created_at,
            plan_id=200,
            kind=TeamKind.DEPARTMENT,
            status=TeamStatus.ACTIVE,
            privacy="public",
            plan_end_date=None,
        )

        assert team.plan_end_date is None

    def test_team_entity_with_none_stripe_fields(self) -> None:
        """Should accept None for stripe fields."""
        workspace_id = uuid4()
        created_at = datetime.datetime(2024, 1, 1, 12, 0, 0)

        team = TeamEntity(
            id=19,
            workspace_id=workspace_id,
            title="No Stripe Team",
            created_by_id=62,
            created_at=created_at,
            plan_id=210,
            kind=TeamKind.DEPARTMENT,
            status=TeamStatus.ACTIVE,
            privacy="public",
            stripe_customer_id=None,
            stripe_subscription_id=None,
        )

        assert team.stripe_customer_id is None
        assert team.stripe_subscription_id is None

    def test_team_entity_with_different_workspace_ids(self) -> None:
        """Should maintain distinct workspace_id values."""
        created_at = datetime.datetime(2024, 1, 1, 12, 0, 0)
        workspace_id_1 = uuid4()
        workspace_id_2 = uuid4()

        team1 = TeamEntity(
            id=20,
            workspace_id=workspace_id_1,
            title="Team in Workspace 1",
            created_by_id=63,
            created_at=created_at,
            plan_id=220,
            kind=TeamKind.DEPARTMENT,
            status=TeamStatus.ACTIVE,
            privacy="public",
        )

        team2 = TeamEntity(
            id=21,
            workspace_id=workspace_id_2,
            title="Team in Workspace 2",
            created_by_id=64,
            created_at=created_at,
            plan_id=230,
            kind=TeamKind.DEPARTMENT,
            status=TeamStatus.ACTIVE,
            privacy="public",
        )

        assert team1.workspace_id != team2.workspace_id
        assert team1.workspace_id == workspace_id_1
        assert team2.workspace_id == workspace_id_2

    def test_team_entity_datetime_fields_preserve_microseconds(self) -> None:
        """Should preserve datetime with microsecond precision."""
        workspace_id = uuid4()
        created_at = datetime.datetime(2024, 1, 1, 12, 30, 45, 123456)

        team = TeamEntity(
            id=22,
            workspace_id=workspace_id,
            title="Precise Time Team",
            created_by_id=65,
            created_at=created_at,
            plan_id=240,
            kind=TeamKind.DEPARTMENT,
            status=TeamStatus.ACTIVE,
            privacy="public",
        )

        assert team.created_at.microsecond == 123456
        assert team.created_at == created_at


class TestTeamEntityEquality:
    """Tests for TeamEntity equality and identity."""

    def test_two_team_entities_with_same_values_are_equal(self) -> None:
        """Should consider two entities with identical field values as equal."""
        workspace_id = uuid4()
        created_at = datetime.datetime(2024, 1, 1, 12, 0, 0)

        team1 = TeamEntity(
            id=23,
            workspace_id=workspace_id,
            title="Identical Team",
            created_by_id=66,
            created_at=created_at,
            plan_id=250,
            kind=TeamKind.DEPARTMENT,
            status=TeamStatus.ACTIVE,
            privacy="public",
        )

        team2 = TeamEntity(
            id=23,
            workspace_id=workspace_id,
            title="Identical Team",
            created_by_id=66,
            created_at=created_at,
            plan_id=250,
            kind=TeamKind.DEPARTMENT,
            status=TeamStatus.ACTIVE,
            privacy="public",
        )

        assert team1 == team2

    def test_two_team_entities_with_different_ids_are_not_equal(self) -> None:
        """Should consider entities with different ids as unequal."""
        workspace_id = uuid4()
        created_at = datetime.datetime(2024, 1, 1, 12, 0, 0)

        team1 = TeamEntity(
            id=24,
            workspace_id=workspace_id,
            title="Same Team",
            created_by_id=67,
            created_at=created_at,
            plan_id=260,
            kind=TeamKind.DEPARTMENT,
            status=TeamStatus.ACTIVE,
            privacy="public",
        )

        team2 = TeamEntity(
            id=25,
            workspace_id=workspace_id,
            title="Same Team",
            created_by_id=67,
            created_at=created_at,
            plan_id=260,
            kind=TeamKind.DEPARTMENT,
            status=TeamStatus.ACTIVE,
            privacy="public",
        )

        assert team1 != team2
