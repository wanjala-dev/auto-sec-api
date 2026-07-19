"""Unit tests for InvitationEntity."""

from __future__ import annotations

import datetime
from dataclasses import FrozenInstanceError
from uuid import uuid4

import pytest

from components.membership.domain.entities.invitation_entity import InvitationEntity
from components.team.domain.enums import InvitationStatus


class TestInvitationEntity:
    """Tests for InvitationEntity."""

    def test_construct_with_all_fields(self) -> None:
        """Test constructing an invitation with all fields."""
        workspace_id = uuid4()
        date_sent = datetime.datetime.now(tz=datetime.UTC)
        accepted_at = datetime.datetime.now(tz=datetime.UTC)

        invitation = InvitationEntity(
            id=1,
            workspace_id=workspace_id,
            team_id=10,
            email="user@example.com",
            code="ABC123",
            status=InvitationStatus.INVITED,
            date_sent=date_sent,
            accepted_at=accepted_at,
        )

        assert invitation.id == 1
        assert invitation.workspace_id == workspace_id
        assert invitation.team_id == 10
        assert invitation.email == "user@example.com"
        assert invitation.code == "ABC123"
        assert invitation.status == InvitationStatus.INVITED
        assert invitation.date_sent == date_sent
        assert invitation.accepted_at == accepted_at

    def test_construct_with_none_accepted_at(self) -> None:
        """Test constructing an invitation without accepted_at."""
        workspace_id = uuid4()
        date_sent = datetime.datetime.now(tz=datetime.UTC)

        invitation = InvitationEntity(
            id=2,
            workspace_id=workspace_id,
            team_id=11,
            email="another@example.com",
            code="DEF456",
            status=InvitationStatus.INVITED,
            date_sent=date_sent,
        )

        assert invitation.accepted_at is None

    def test_construct_raises_on_empty_email(self) -> None:
        """Test that constructing with empty email raises ValueError."""
        workspace_id = uuid4()
        date_sent = datetime.datetime.now(tz=datetime.UTC)

        with pytest.raises(ValueError, match="InvitationEntity.email is required"):
            InvitationEntity(
                id=3,
                workspace_id=workspace_id,
                team_id=12,
                email="",
                code="GHI789",
                status=InvitationStatus.INVITED,
                date_sent=date_sent,
            )

    def test_construct_raises_on_none_email(self) -> None:
        """Test that constructing with None email raises ValueError."""
        workspace_id = uuid4()
        date_sent = datetime.datetime.now(tz=datetime.UTC)

        with pytest.raises(ValueError, match="InvitationEntity.email is required"):
            InvitationEntity(
                id=4,
                workspace_id=workspace_id,
                team_id=13,
                email=None,  # type: ignore
                code="JKL012",
                status=InvitationStatus.INVITED,
                date_sent=date_sent,
            )

    def test_is_pending_when_status_invited(self) -> None:
        """Test is_pending property returns True when status is INVITED."""
        workspace_id = uuid4()
        date_sent = datetime.datetime.now(tz=datetime.UTC)

        invitation = InvitationEntity(
            id=5,
            workspace_id=workspace_id,
            team_id=14,
            email="pending@example.com",
            code="MNO345",
            status=InvitationStatus.INVITED,
            date_sent=date_sent,
        )

        assert invitation.is_pending is True

    def test_is_pending_when_status_accepted(self) -> None:
        """Test is_pending property returns False when status is ACCEPTED."""
        workspace_id = uuid4()
        date_sent = datetime.datetime.now(tz=datetime.UTC)
        accepted_at = datetime.datetime.now(tz=datetime.UTC)

        invitation = InvitationEntity(
            id=6,
            workspace_id=workspace_id,
            team_id=15,
            email="accepted@example.com",
            code="PQR678",
            status=InvitationStatus.ACCEPTED,
            date_sent=date_sent,
            accepted_at=accepted_at,
        )

        assert invitation.is_pending is False

    def test_is_accepted_when_status_accepted(self) -> None:
        """Test is_accepted property returns True when status is ACCEPTED."""
        workspace_id = uuid4()
        date_sent = datetime.datetime.now(tz=datetime.UTC)
        accepted_at = datetime.datetime.now(tz=datetime.UTC)

        invitation = InvitationEntity(
            id=7,
            workspace_id=workspace_id,
            team_id=16,
            email="accepted2@example.com",
            code="STU901",
            status=InvitationStatus.ACCEPTED,
            date_sent=date_sent,
            accepted_at=accepted_at,
        )

        assert invitation.is_accepted is True

    def test_is_accepted_when_status_invited(self) -> None:
        """Test is_accepted property returns False when status is INVITED."""
        workspace_id = uuid4()
        date_sent = datetime.datetime.now(tz=datetime.UTC)

        invitation = InvitationEntity(
            id=8,
            workspace_id=workspace_id,
            team_id=17,
            email="notaccepted@example.com",
            code="VWX234",
            status=InvitationStatus.INVITED,
            date_sent=date_sent,
        )

        assert invitation.is_accepted is False

    def test_entity_is_frozen(self) -> None:
        """Test that InvitationEntity is immutable."""
        workspace_id = uuid4()
        date_sent = datetime.datetime.now(tz=datetime.UTC)

        invitation = InvitationEntity(
            id=9,
            workspace_id=workspace_id,
            team_id=18,
            email="frozen@example.com",
            code="YZA567",
            status=InvitationStatus.INVITED,
            date_sent=date_sent,
        )

        with pytest.raises(FrozenInstanceError):
            invitation.status = InvitationStatus.ACCEPTED

    def test_entity_equality(self) -> None:
        """Test that two entities with same data are equal."""
        workspace_id = uuid4()
        date_sent = datetime.datetime.now(tz=datetime.UTC)

        invitation1 = InvitationEntity(
            id=10,
            workspace_id=workspace_id,
            team_id=19,
            email="equal@example.com",
            code="BCD890",
            status=InvitationStatus.INVITED,
            date_sent=date_sent,
        )

        invitation2 = InvitationEntity(
            id=10,
            workspace_id=workspace_id,
            team_id=19,
            email="equal@example.com",
            code="BCD890",
            status=InvitationStatus.INVITED,
            date_sent=date_sent,
        )

        assert invitation1 == invitation2

    def test_entity_inequality_different_id(self) -> None:
        """Test that entities with different IDs are not equal."""
        workspace_id = uuid4()
        date_sent = datetime.datetime.now(tz=datetime.UTC)

        invitation1 = InvitationEntity(
            id=11,
            workspace_id=workspace_id,
            team_id=20,
            email="notequal@example.com",
            code="EFG123",
            status=InvitationStatus.INVITED,
            date_sent=date_sent,
        )

        invitation2 = InvitationEntity(
            id=12,
            workspace_id=workspace_id,
            team_id=20,
            email="notequal@example.com",
            code="EFG123",
            status=InvitationStatus.INVITED,
            date_sent=date_sent,
        )

        assert invitation1 != invitation2

    def test_entity_inequality_different_email(self) -> None:
        """Test that entities with different emails are not equal."""
        workspace_id = uuid4()
        date_sent = datetime.datetime.now(tz=datetime.UTC)

        invitation1 = InvitationEntity(
            id=13,
            workspace_id=workspace_id,
            team_id=21,
            email="first@example.com",
            code="HIJ456",
            status=InvitationStatus.INVITED,
            date_sent=date_sent,
        )

        invitation2 = InvitationEntity(
            id=13,
            workspace_id=workspace_id,
            team_id=21,
            email="second@example.com",
            code="HIJ456",
            status=InvitationStatus.INVITED,
            date_sent=date_sent,
        )

        assert invitation1 != invitation2

    def test_email_with_valid_format(self) -> None:
        """Test constructing with various valid email formats."""
        workspace_id = uuid4()
        date_sent = datetime.datetime.now(tz=datetime.UTC)

        emails = [
            "simple@example.com",
            "with.dot@example.com",
            "with+plus@example.co.uk",
            "123@example.com",
        ]

        for email in emails:
            invitation = InvitationEntity(
                id=99,
                workspace_id=workspace_id,
                team_id=99,
                email=email,
                code="TEST123",
                status=InvitationStatus.INVITED,
                date_sent=date_sent,
            )
            assert invitation.email == email

    def test_post_init_validation_order(self) -> None:
        """Test that post_init validation runs after field initialization."""
        workspace_id = uuid4()
        date_sent = datetime.datetime.now(tz=datetime.UTC)

        # This should not raise; the whitespace is preserved
        invitation = InvitationEntity(
            id=14,
            workspace_id=workspace_id,
            team_id=22,
            email=" ",  # Single space is not empty string
            code="KLM789",
            status=InvitationStatus.INVITED,
            date_sent=date_sent,
        )

        assert invitation.email == " "
        assert invitation.is_pending is True

    def test_accepted_at_can_be_before_date_sent(self) -> None:
        """Test that accepted_at can technically be before date_sent (no validation)."""
        workspace_id = uuid4()
        date_sent = datetime.datetime(2025, 1, 1, tzinfo=datetime.UTC)
        # Earlier than date_sent, but no validation is done on the domain
        accepted_at = datetime.datetime(2024, 12, 31, tzinfo=datetime.UTC)

        invitation = InvitationEntity(
            id=15,
            workspace_id=workspace_id,
            team_id=23,
            email="timetravel@example.com",
            code="NOP012",
            status=InvitationStatus.ACCEPTED,
            date_sent=date_sent,
            accepted_at=accepted_at,
        )

        assert invitation.accepted_at == accepted_at
