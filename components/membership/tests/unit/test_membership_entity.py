"""Unit tests for WorkspaceMembershipEntity and TeamMembershipEntity."""

from __future__ import annotations

import datetime
from dataclasses import FrozenInstanceError
from uuid import uuid4

import pytest

from components.membership.domain.entities.membership_entity import (
    TeamMembershipEntity,
    WorkspaceMembershipEntity,
)
from components.membership.domain.enums import (
    WorkspaceMembershipRole,
    WorkspaceMembershipStatus,
)
from components.team.domain.enums import TeamMembershipRole, TeamMembershipStatus


class TestWorkspaceMembershipEntity:
    """Tests for WorkspaceMembershipEntity."""

    def test_construct_with_all_fields(self) -> None:
        """Test constructing a workspace membership with all fields."""
        workspace_id = uuid4()
        created_at = datetime.datetime.now(tz=datetime.UTC)
        updated_at = datetime.datetime.now(tz=datetime.UTC)

        membership = WorkspaceMembershipEntity(
            id=1,
            workspace_id=workspace_id,
            user_id=42,
            role=WorkspaceMembershipRole.ADMIN,
            status=WorkspaceMembershipStatus.ACTIVE,
            created_at=created_at,
            updated_at=updated_at,
            invited_by_id=10,
        )

        assert membership.id == 1
        assert membership.workspace_id == workspace_id
        assert membership.user_id == 42
        assert membership.role == WorkspaceMembershipRole.ADMIN
        assert membership.status == WorkspaceMembershipStatus.ACTIVE
        assert membership.created_at == created_at
        assert membership.updated_at == updated_at
        assert membership.invited_by_id == 10

    def test_construct_without_invited_by_id(self) -> None:
        """Test constructing a workspace membership without invited_by_id."""
        workspace_id = uuid4()
        created_at = datetime.datetime.now(tz=datetime.UTC)
        updated_at = datetime.datetime.now(tz=datetime.UTC)

        membership = WorkspaceMembershipEntity(
            id=2,
            workspace_id=workspace_id,
            user_id=43,
            role=WorkspaceMembershipRole.MEMBER,
            status=WorkspaceMembershipStatus.ACTIVE,
            created_at=created_at,
            updated_at=updated_at,
        )

        assert membership.invited_by_id is None

    def test_is_active_when_status_active(self) -> None:
        """Test is_active property returns True when status is ACTIVE."""
        workspace_id = uuid4()
        created_at = datetime.datetime.now(tz=datetime.UTC)
        updated_at = datetime.datetime.now(tz=datetime.UTC)

        membership = WorkspaceMembershipEntity(
            id=3,
            workspace_id=workspace_id,
            user_id=44,
            role=WorkspaceMembershipRole.MEMBER,
            status=WorkspaceMembershipStatus.ACTIVE,
            created_at=created_at,
            updated_at=updated_at,
        )

        assert membership.is_active is True

    def test_is_active_when_status_invited(self) -> None:
        """Test is_active property returns False when status is INVITED."""
        workspace_id = uuid4()
        created_at = datetime.datetime.now(tz=datetime.UTC)
        updated_at = datetime.datetime.now(tz=datetime.UTC)

        membership = WorkspaceMembershipEntity(
            id=4,
            workspace_id=workspace_id,
            user_id=45,
            role=WorkspaceMembershipRole.MEMBER,
            status=WorkspaceMembershipStatus.INVITED,
            created_at=created_at,
            updated_at=updated_at,
        )

        assert membership.is_active is False

    def test_is_active_when_status_suspended(self) -> None:
        """Test is_active property returns False when status is SUSPENDED."""
        workspace_id = uuid4()
        created_at = datetime.datetime.now(tz=datetime.UTC)
        updated_at = datetime.datetime.now(tz=datetime.UTC)

        membership = WorkspaceMembershipEntity(
            id=5,
            workspace_id=workspace_id,
            user_id=46,
            role=WorkspaceMembershipRole.MEMBER,
            status=WorkspaceMembershipStatus.SUSPENDED,
            created_at=created_at,
            updated_at=updated_at,
        )

        assert membership.is_active is False

    def test_is_owner_when_role_owner(self) -> None:
        """Test is_owner property returns True when role is OWNER."""
        workspace_id = uuid4()
        created_at = datetime.datetime.now(tz=datetime.UTC)
        updated_at = datetime.datetime.now(tz=datetime.UTC)

        membership = WorkspaceMembershipEntity(
            id=6,
            workspace_id=workspace_id,
            user_id=47,
            role=WorkspaceMembershipRole.OWNER,
            status=WorkspaceMembershipStatus.ACTIVE,
            created_at=created_at,
            updated_at=updated_at,
        )

        assert membership.is_owner is True

    def test_is_owner_when_role_admin(self) -> None:
        """Test is_owner property returns False when role is ADMIN."""
        workspace_id = uuid4()
        created_at = datetime.datetime.now(tz=datetime.UTC)
        updated_at = datetime.datetime.now(tz=datetime.UTC)

        membership = WorkspaceMembershipEntity(
            id=7,
            workspace_id=workspace_id,
            user_id=48,
            role=WorkspaceMembershipRole.ADMIN,
            status=WorkspaceMembershipStatus.ACTIVE,
            created_at=created_at,
            updated_at=updated_at,
        )

        assert membership.is_owner is False

    def test_is_owner_when_role_member(self) -> None:
        """Test is_owner property returns False when role is MEMBER."""
        workspace_id = uuid4()
        created_at = datetime.datetime.now(tz=datetime.UTC)
        updated_at = datetime.datetime.now(tz=datetime.UTC)

        membership = WorkspaceMembershipEntity(
            id=8,
            workspace_id=workspace_id,
            user_id=49,
            role=WorkspaceMembershipRole.MEMBER,
            status=WorkspaceMembershipStatus.ACTIVE,
            created_at=created_at,
            updated_at=updated_at,
        )

        assert membership.is_owner is False

    def test_is_owner_when_role_viewer(self) -> None:
        """Test is_owner property returns False when role is VIEWER."""
        workspace_id = uuid4()
        created_at = datetime.datetime.now(tz=datetime.UTC)
        updated_at = datetime.datetime.now(tz=datetime.UTC)

        membership = WorkspaceMembershipEntity(
            id=9,
            workspace_id=workspace_id,
            user_id=50,
            role=WorkspaceMembershipRole.VIEWER,
            status=WorkspaceMembershipStatus.ACTIVE,
            created_at=created_at,
            updated_at=updated_at,
        )

        assert membership.is_owner is False

    def test_can_manage_when_role_owner(self) -> None:
        """Test can_manage property returns True when role is OWNER."""
        workspace_id = uuid4()
        created_at = datetime.datetime.now(tz=datetime.UTC)
        updated_at = datetime.datetime.now(tz=datetime.UTC)

        membership = WorkspaceMembershipEntity(
            id=10,
            workspace_id=workspace_id,
            user_id=51,
            role=WorkspaceMembershipRole.OWNER,
            status=WorkspaceMembershipStatus.ACTIVE,
            created_at=created_at,
            updated_at=updated_at,
        )

        assert membership.can_manage is True

    def test_can_manage_when_role_admin(self) -> None:
        """Test can_manage property returns True when role is ADMIN."""
        workspace_id = uuid4()
        created_at = datetime.datetime.now(tz=datetime.UTC)
        updated_at = datetime.datetime.now(tz=datetime.UTC)

        membership = WorkspaceMembershipEntity(
            id=11,
            workspace_id=workspace_id,
            user_id=52,
            role=WorkspaceMembershipRole.ADMIN,
            status=WorkspaceMembershipStatus.ACTIVE,
            created_at=created_at,
            updated_at=updated_at,
        )

        assert membership.can_manage is True

    def test_can_manage_when_role_member(self) -> None:
        """Test can_manage property returns False when role is MEMBER."""
        workspace_id = uuid4()
        created_at = datetime.datetime.now(tz=datetime.UTC)
        updated_at = datetime.datetime.now(tz=datetime.UTC)

        membership = WorkspaceMembershipEntity(
            id=12,
            workspace_id=workspace_id,
            user_id=53,
            role=WorkspaceMembershipRole.MEMBER,
            status=WorkspaceMembershipStatus.ACTIVE,
            created_at=created_at,
            updated_at=updated_at,
        )

        assert membership.can_manage is False

    def test_can_manage_when_role_viewer(self) -> None:
        """Test can_manage property returns False when role is VIEWER."""
        workspace_id = uuid4()
        created_at = datetime.datetime.now(tz=datetime.UTC)
        updated_at = datetime.datetime.now(tz=datetime.UTC)

        membership = WorkspaceMembershipEntity(
            id=13,
            workspace_id=workspace_id,
            user_id=54,
            role=WorkspaceMembershipRole.VIEWER,
            status=WorkspaceMembershipStatus.ACTIVE,
            created_at=created_at,
            updated_at=updated_at,
        )

        assert membership.can_manage is False

    def test_entity_is_frozen(self) -> None:
        """Test that WorkspaceMembershipEntity is immutable."""
        workspace_id = uuid4()
        created_at = datetime.datetime.now(tz=datetime.UTC)
        updated_at = datetime.datetime.now(tz=datetime.UTC)

        membership = WorkspaceMembershipEntity(
            id=14,
            workspace_id=workspace_id,
            user_id=55,
            role=WorkspaceMembershipRole.MEMBER,
            status=WorkspaceMembershipStatus.ACTIVE,
            created_at=created_at,
            updated_at=updated_at,
        )

        with pytest.raises(FrozenInstanceError):
            membership.role = WorkspaceMembershipRole.ADMIN

    def test_entity_equality(self) -> None:
        """Test that two entities with same data are equal."""
        workspace_id = uuid4()
        created_at = datetime.datetime.now(tz=datetime.UTC)
        updated_at = datetime.datetime.now(tz=datetime.UTC)

        membership1 = WorkspaceMembershipEntity(
            id=15,
            workspace_id=workspace_id,
            user_id=56,
            role=WorkspaceMembershipRole.MEMBER,
            status=WorkspaceMembershipStatus.ACTIVE,
            created_at=created_at,
            updated_at=updated_at,
        )

        membership2 = WorkspaceMembershipEntity(
            id=15,
            workspace_id=workspace_id,
            user_id=56,
            role=WorkspaceMembershipRole.MEMBER,
            status=WorkspaceMembershipStatus.ACTIVE,
            created_at=created_at,
            updated_at=updated_at,
        )

        assert membership1 == membership2

    def test_entity_inequality_different_id(self) -> None:
        """Test that entities with different IDs are not equal."""
        workspace_id = uuid4()
        created_at = datetime.datetime.now(tz=datetime.UTC)
        updated_at = datetime.datetime.now(tz=datetime.UTC)

        membership1 = WorkspaceMembershipEntity(
            id=16,
            workspace_id=workspace_id,
            user_id=57,
            role=WorkspaceMembershipRole.MEMBER,
            status=WorkspaceMembershipStatus.ACTIVE,
            created_at=created_at,
            updated_at=updated_at,
        )

        membership2 = WorkspaceMembershipEntity(
            id=17,
            workspace_id=workspace_id,
            user_id=57,
            role=WorkspaceMembershipRole.MEMBER,
            status=WorkspaceMembershipStatus.ACTIVE,
            created_at=created_at,
            updated_at=updated_at,
        )

        assert membership1 != membership2


class TestTeamMembershipEntity:
    """Tests for TeamMembershipEntity."""

    def test_construct_with_all_fields(self) -> None:
        """Test constructing a team membership with all fields."""
        created_at = datetime.datetime.now(tz=datetime.UTC)
        updated_at = datetime.datetime.now(tz=datetime.UTC)

        membership = TeamMembershipEntity(
            id=100,
            team_id=1,
            user_id=58,
            role=TeamMembershipRole.LEAD,
            status=TeamMembershipStatus.ACTIVE,
            created_at=created_at,
            updated_at=updated_at,
        )

        assert membership.id == 100
        assert membership.team_id == 1
        assert membership.user_id == 58
        assert membership.role == TeamMembershipRole.LEAD
        assert membership.status == TeamMembershipStatus.ACTIVE
        assert membership.created_at == created_at
        assert membership.updated_at == updated_at

    def test_is_active_when_status_active(self) -> None:
        """Test is_active property returns True when status is ACTIVE."""
        created_at = datetime.datetime.now(tz=datetime.UTC)
        updated_at = datetime.datetime.now(tz=datetime.UTC)

        membership = TeamMembershipEntity(
            id=101,
            team_id=2,
            user_id=59,
            role=TeamMembershipRole.EDITOR,
            status=TeamMembershipStatus.ACTIVE,
            created_at=created_at,
            updated_at=updated_at,
        )

        assert membership.is_active is True

    def test_is_active_when_status_suspended(self) -> None:
        """Test is_active property returns False when status is SUSPENDED."""
        created_at = datetime.datetime.now(tz=datetime.UTC)
        updated_at = datetime.datetime.now(tz=datetime.UTC)

        membership = TeamMembershipEntity(
            id=102,
            team_id=3,
            user_id=60,
            role=TeamMembershipRole.EDITOR,
            status=TeamMembershipStatus.SUSPENDED,
            created_at=created_at,
            updated_at=updated_at,
        )

        assert membership.is_active is False

    def test_is_lead_when_role_lead(self) -> None:
        """Test is_lead property returns True when role is LEAD."""
        created_at = datetime.datetime.now(tz=datetime.UTC)
        updated_at = datetime.datetime.now(tz=datetime.UTC)

        membership = TeamMembershipEntity(
            id=103,
            team_id=4,
            user_id=61,
            role=TeamMembershipRole.LEAD,
            status=TeamMembershipStatus.ACTIVE,
            created_at=created_at,
            updated_at=updated_at,
        )

        assert membership.is_lead is True

    def test_is_lead_when_role_editor(self) -> None:
        """Test is_lead property returns False when role is EDITOR."""
        created_at = datetime.datetime.now(tz=datetime.UTC)
        updated_at = datetime.datetime.now(tz=datetime.UTC)

        membership = TeamMembershipEntity(
            id=104,
            team_id=5,
            user_id=62,
            role=TeamMembershipRole.EDITOR,
            status=TeamMembershipStatus.ACTIVE,
            created_at=created_at,
            updated_at=updated_at,
        )

        assert membership.is_lead is False

    def test_is_lead_when_role_viewer(self) -> None:
        """Test is_lead property returns False when role is VIEWER."""
        created_at = datetime.datetime.now(tz=datetime.UTC)
        updated_at = datetime.datetime.now(tz=datetime.UTC)

        membership = TeamMembershipEntity(
            id=105,
            team_id=6,
            user_id=63,
            role=TeamMembershipRole.VIEWER,
            status=TeamMembershipStatus.ACTIVE,
            created_at=created_at,
            updated_at=updated_at,
        )

        assert membership.is_lead is False

    def test_entity_is_frozen(self) -> None:
        """Test that TeamMembershipEntity is immutable."""
        created_at = datetime.datetime.now(tz=datetime.UTC)
        updated_at = datetime.datetime.now(tz=datetime.UTC)

        membership = TeamMembershipEntity(
            id=106,
            team_id=7,
            user_id=64,
            role=TeamMembershipRole.EDITOR,
            status=TeamMembershipStatus.ACTIVE,
            created_at=created_at,
            updated_at=updated_at,
        )

        with pytest.raises(FrozenInstanceError):
            membership.role = TeamMembershipRole.LEAD

    def test_entity_equality(self) -> None:
        """Test that two entities with same data are equal."""
        created_at = datetime.datetime.now(tz=datetime.UTC)
        updated_at = datetime.datetime.now(tz=datetime.UTC)

        membership1 = TeamMembershipEntity(
            id=107,
            team_id=8,
            user_id=65,
            role=TeamMembershipRole.EDITOR,
            status=TeamMembershipStatus.ACTIVE,
            created_at=created_at,
            updated_at=updated_at,
        )

        membership2 = TeamMembershipEntity(
            id=107,
            team_id=8,
            user_id=65,
            role=TeamMembershipRole.EDITOR,
            status=TeamMembershipStatus.ACTIVE,
            created_at=created_at,
            updated_at=updated_at,
        )

        assert membership1 == membership2

    def test_entity_inequality_different_user_id(self) -> None:
        """Test that entities with different user IDs are not equal."""
        created_at = datetime.datetime.now(tz=datetime.UTC)
        updated_at = datetime.datetime.now(tz=datetime.UTC)

        membership1 = TeamMembershipEntity(
            id=108,
            team_id=9,
            user_id=66,
            role=TeamMembershipRole.EDITOR,
            status=TeamMembershipStatus.ACTIVE,
            created_at=created_at,
            updated_at=updated_at,
        )

        membership2 = TeamMembershipEntity(
            id=108,
            team_id=9,
            user_id=67,
            role=TeamMembershipRole.EDITOR,
            status=TeamMembershipStatus.ACTIVE,
            created_at=created_at,
            updated_at=updated_at,
        )

        assert membership1 != membership2
